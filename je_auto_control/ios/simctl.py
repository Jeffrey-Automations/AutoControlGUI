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
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from je_auto_control.wrapper.device_context import (
    STATE_AVAILABLE, STATE_NEEDS_DEPENDENCY, STATE_UNSUPPORTED, DeviceCapability, DeviceError,
    DeviceTimeoutError, DeviceUnsupportedError,
)

_UDID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
_BUNDLE = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_TIMEOUT_S = 120.0
_FEATURES = ("install", "files", "clipboard", "recording")
_NO_XCRUN = "xcrun simctl needs macOS with Xcode's command line tools"
Runner = Callable[..., Any]


@dataclass
class _Recording:
    """One ``recordVideo`` process, the host file it writes and the timer that ends it."""

    process: Any
    path: str
    timer: Optional[threading.Timer] = None


# Keyed by UDID, not held by an extension: every command builds its own extension, so the one
# that stops a recording is never the one that started it.
_RECORDINGS: Dict[str, _Recording] = {}
_RECORDINGS_LOCK = threading.Lock()


def _udid(value: Any) -> str:
    if not isinstance(value, str) or _UDID.fullmatch(value) is None:
        raise DeviceError("an iOS Simulator UDID is required (xcrun simctl list devices)")
    return value.upper()


def _simctl_available() -> bool:
    return sys.platform == "darwin" and shutil.which("xcrun") is not None


def _run_simctl(runner: Runner, *arguments: str, data: Optional[str] = None) -> str:
    """Run one bounded ``simctl`` command and return its output; every failure is a device error."""
    try:
        # Bytes, not text mode: pasteboard text must keep its carriage returns.
        result = runner(["xcrun", "simctl", *arguments], capture_output=True, timeout=_TIMEOUT_S, check=False,
                        shell=False,  # nosec B603  # reason: fixed simctl argv, no shell
                        input=None if data is None else data.encode("utf-8"))
    except subprocess.TimeoutExpired:
        raise DeviceTimeoutError(f"xcrun simctl {arguments[0]} timed out after {_TIMEOUT_S:g}s") from None
    except OSError as error:
        raise DeviceError(f"xcrun simctl {arguments[0]} could not start") from error
    if result.returncode != 0:
        raise DeviceError(f"xcrun simctl {arguments[0]} failed with exit code {result.returncode}")
    output = result.stdout or b""
    return output.decode("utf-8", "replace") if isinstance(output, bytes) else str(output)


def _time_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DeviceError(f"time_limit_s must be a whole number of seconds, or 0 for no limit, got {value!r}")
    return value


def _interrupt(process: Any) -> None:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)  # recordVideo finalizes the file on SIGINT


class SimctlExtension:
    """The extension surface for one booted iOS Simulator."""

    name = "simctl"

    def __init__(self, udid: str, *, runner: Runner = subprocess.run,
                 popen: Callable[..., Any] = subprocess.Popen,
                 available: Callable[[], bool] = _simctl_available) -> None:
        self._udid = _udid(udid)
        self._run, self._popen, self._available = runner, popen, available

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
        return _run_simctl(self._run, *arguments, data=data)

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
        container = self._simctl("get_app_container", self._udid, bundle, "data").strip()
        if not os.path.isabs(container):  # realpath("") would be this process's working directory
            raise DeviceError("xcrun simctl reported no data container for the app")
        root = os.path.realpath(container)
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
        os.makedirs(os.path.dirname(target), exist_ok=True)
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
        limit = _time_limit(time_limit_s)
        with _RECORDINGS_LOCK:
            if self._udid in _RECORDINGS:
                raise DeviceError("a Simulator recording is already running")
            handle, path = tempfile.mkstemp(suffix=".mp4", prefix="je-simctl-")
            os.close(handle)
            os.unlink(path)  # recordVideo refuses an existing file
            try:
                process = self._popen(  # nosec B603  # reason: fixed simctl argv, no shell
                    ["xcrun", "simctl", "io", self._udid, "recordVideo", "--force", path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)
            except OSError as error:
                raise DeviceError("xcrun simctl io could not start") from error
            recording = _RECORDINGS[self._udid] = _Recording(process, path)
            if limit:
                # Bound to this process: a later recording must not inherit an earlier limit.
                recording.timer = threading.Timer(limit, _interrupt, (process,))
                recording.timer.daemon = True
                recording.timer.start()
        return path

    def stop_recording(self, local_path: str, remote_path: str = "") -> str:
        """Stop the recording, let ``simctl`` finish the file, and move it to ``local_path``."""
        del remote_path
        with _RECORDINGS_LOCK:
            recording = _RECORDINGS.pop(self._udid, None)
        if recording is None:
            raise DeviceError("no Simulator recording is running")
        if recording.timer is not None:
            recording.timer.cancel()
        process = recording.process
        _interrupt(process)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise DeviceError("the Simulator recording did not finish its file") from None
        if not os.path.isfile(recording.path):
            raise DeviceError("the Simulator recording produced no file")
        target = os.path.realpath(local_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.move(recording.path, target)
        return target


def list_ios_simulators(*, runner: Runner = subprocess.run) -> List[Dict[str, str]]:
    """Booted iOS Simulators as ``{udid, name, runtime}``; empty where ``simctl`` is unavailable."""
    if not _simctl_available() and runner is subprocess.run:
        return []
    output = _run_simctl(runner, "list", "devices", "booted", "-j")
    try:
        devices = json.loads(output or "{}").get("devices", {})
    except (ValueError, AttributeError):
        raise DeviceError("xcrun simctl list returned no device list") from None
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
