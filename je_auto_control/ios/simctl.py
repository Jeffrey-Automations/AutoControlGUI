"""Install, files, pasteboard and screen recording for iOS Simulators through Xcode's ``xcrun simctl``.

WebDriverAgent offers none of install / files / recording, and reads the pasteboard only by
switching apps. For a Simulator, ``xcrun simctl`` provides all four on the host, so this adapter
is registered with :func:`use_ios_simulator` and layered over the WebDriverAgent extension by
:func:`~je_auto_control.wrapper.mobile_extensions.mobile_extension`. It never touches a physical
device: ``simctl`` addresses Simulators only. Every call is a fixed argv with a timeout and no
shell, and device paths are ``<bundle id>:<path>`` inside that app's data container, resolved and
bounded so ``..`` or a link cannot leave it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess  # nosec B404  # reason: fixed xcrun simctl argv, never a shell or caller-built command
import sys
import tempfile
import threading
from typing import Any, Callable, Dict, List, Optional

from je_auto_control.wrapper.device_context import (
    STATE_AVAILABLE, STATE_NEEDS_DEPENDENCY, STATE_UNSUPPORTED, DeviceCapability, DeviceError,
    DeviceUnsupportedError,
)

_UDID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
_BUNDLE = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_TIMEOUT_S = 120.0
_FEATURES = ("install", "files", "clipboard", "recording")
_NO_XCRUN = "xcrun simctl needs macOS with Xcode's command line tools"
Runner = Callable[..., Any]


def _udid(value: Any) -> str:
    if not isinstance(value, str) or _UDID.fullmatch(value) is None:
        raise DeviceError("an iOS Simulator UDID is required (xcrun simctl list devices)")
    return value.upper()


def _simctl_available() -> bool:
    return sys.platform == "darwin" and shutil.which("xcrun") is not None


class SimctlExtension:
    """The extension surface for one booted iOS Simulator."""

    name = "simctl"

    def __init__(self, udid: str, *, runner: Runner = subprocess.run,
                 popen: Callable[..., Any] = subprocess.Popen,
                 available: Callable[[], bool] = _simctl_available) -> None:
        self._udid = _udid(udid)
        self._run, self._popen, self._available = runner, popen, available
        self._recording: Optional[Any] = None
        self._recording_path: Optional[str] = None
        self._lock = threading.Lock()

    def capability(self, feature: str) -> DeviceCapability:
        """Whether ``feature`` can be used; this never runs ``simctl``."""
        if feature not in _FEATURES:
            return DeviceCapability(feature, STATE_UNSUPPORTED, f"unknown feature {feature!r}")
        if not self._available():
            return DeviceCapability(feature, STATE_NEEDS_DEPENDENCY, _NO_XCRUN)
        return DeviceCapability(feature, STATE_AVAILABLE, f"xcrun simctl on Simulator {self._udid}")

    def _require(self, feature: str) -> None:
        status = self.capability(feature)
        if not status.available:
            raise DeviceUnsupportedError(f"{feature} is not available: {status.reason}", reason=status.reason)

    def _simctl(self, *arguments: str, data: Optional[str] = None) -> str:
        argv = ["xcrun", "simctl", *arguments]
        result = self._run(argv, capture_output=True, text=True, timeout=_TIMEOUT_S, check=False,
                           shell=False, input=data)  # nosec B603  # reason: fixed simctl argv, no shell
        if result.returncode != 0:
            raise DeviceError(f"xcrun simctl {arguments[0]} failed with exit code {result.returncode}")
        return str(result.stdout or "")

    def install_app(self, source: str) -> str:
        """Install the ``.app`` bundle at host path ``source`` on the Simulator."""
        self._require("install")
        path = os.path.realpath(source)
        if not path.endswith(".app") or not os.path.isdir(path):
            raise DeviceError("a Simulator install needs a built .app bundle directory")
        self._simctl("install", self._udid, path)
        return path

    def _container_path(self, remote_path: str) -> str:
        bundle, separator, relative = str(remote_path).partition(":")
        if not separator or _BUNDLE.fullmatch(bundle) is None or not relative:
            raise DeviceError("iOS Simulator paths are '<bundle id>:<path inside its data container>'")
        root = os.path.realpath(self._simctl("get_app_container", self._udid, bundle, "data").strip())
        target = os.path.realpath(os.path.join(root, relative.lstrip("/")))
        if os.path.commonpath([root, target]) != root or target == root:
            raise DeviceError("the path leaves the app's data container")
        return target

    def push_file(self, local_path: str, remote_path: str) -> str:
        """Copy a host file into an app's data container on the Simulator."""
        self._require("files")
        source = os.path.realpath(local_path)
        if not os.path.isfile(source):
            raise DeviceError(f"no host file at {local_path!r}")
        target = self._container_path(remote_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
        return target

    def pull_file(self, remote_path: str, local_path: str) -> str:
        """Copy a file out of an app's data container on the Simulator."""
        self._require("files")
        source = self._container_path(remote_path)
        if not os.path.isfile(source):
            raise DeviceError(f"no file at {remote_path!r} on the Simulator")
        target = os.path.realpath(local_path)
        shutil.copyfile(source, target)
        return target

    def get_clipboard(self, *, allow_app_switch: bool = False) -> str:
        """The Simulator pasteboard's text; ``simctl`` reads it without switching apps."""
        del allow_app_switch
        self._require("clipboard")
        return self._simctl("pbpaste", self._udid)

    def set_clipboard(self, text: str) -> None:
        """Put ``text`` on the Simulator pasteboard."""
        if not isinstance(text, str):
            raise TypeError("clipboard text must be a string")
        self._require("clipboard")
        self._simctl("pbcopy", self._udid, data=text)

    def start_recording(self, remote_path: str = "", time_limit_s: int = 0) -> str:
        """Start ``simctl io recordVideo`` into a host temporary file; ``time_limit_s`` stops it."""
        del remote_path  # simctl records on the host; there is no device-side file
        self._require("recording")
        with self._lock:
            if self._recording is not None:
                raise DeviceError("a Simulator recording is already running")
            handle, path = tempfile.mkstemp(suffix=".mp4", prefix="je-simctl-")
            os.close(handle)
            os.unlink(path)  # recordVideo refuses an existing file
            self._recording = self._popen(  # nosec B603  # reason: fixed simctl argv, no shell
                ["xcrun", "simctl", "io", self._udid, "recordVideo", "--force", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)
            self._recording_path = path
        if time_limit_s:
            timer = threading.Timer(float(time_limit_s), self._interrupt)
            timer.daemon = True
            timer.start()
        return path

    def _interrupt(self) -> None:
        with self._lock:
            process = self._recording
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)  # recordVideo finalizes the file on SIGINT

    def stop_recording(self, local_path: str, remote_path: str = "") -> str:
        """Stop the recording, let ``simctl`` finish the file, and move it to ``local_path``."""
        del remote_path
        with self._lock:
            process, path = self._recording, self._recording_path
            self._recording, self._recording_path = None, None
        if process is None or path is None:
            raise DeviceError("no Simulator recording is running")
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise DeviceError("the Simulator recording did not finish its file") from None
        target = os.path.realpath(local_path)
        shutil.move(path, target)
        return target


def list_ios_simulators(*, runner: Runner = subprocess.run) -> List[Dict[str, str]]:
    """Booted iOS Simulators as ``{udid, name, runtime}``; empty where ``simctl`` is unavailable."""
    if not _simctl_available() and runner is subprocess.run:
        return []
    result = runner(["xcrun", "simctl", "list", "devices", "booted", "-j"], capture_output=True, text=True,
                    timeout=_TIMEOUT_S, check=False, shell=False)  # nosec B603  # reason: fixed argv
    if result.returncode != 0:
        raise DeviceError("xcrun simctl list failed")
    devices = json.loads(result.stdout or "{}").get("devices", {})
    found = []
    for runtime, entries in devices.items():
        for entry in entries:
            if entry.get("state") == "Booted" and _UDID.fullmatch(str(entry.get("udid", ""))):
                found.append({"udid": entry["udid"], "name": str(entry.get("name", "")), "runtime": runtime})
    return found


def use_ios_simulator(udid: Optional[str]) -> Dict[str, Any]:
    """Register ``simctl`` for iOS sessions on Simulator ``udid``; ``None`` or ``""`` removes the registration."""
    # pylint: disable-next=import-outside-toplevel  # reason: keeps the wrapper import graph acyclic
    from je_auto_control.wrapper.mobile_extensions import register_mobile_extension
    if udid is None or udid == "":
        register_mobile_extension("ios", None)
        return {"registered": False}
    chosen = _udid(udid)
    register_mobile_extension("ios", lambda _session: SimctlExtension(chosen))
    probe = SimctlExtension(chosen)
    return {"registered": True, "udid": chosen,
            "capabilities": {feature: probe.capability(feature).state for feature in _FEATURES}}


__all__ = ["SimctlExtension", "list_ios_simulators", "use_ios_simulator"]
