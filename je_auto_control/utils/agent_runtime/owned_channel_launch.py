"""Retain one pinned process channel through measurement, publication and failed retirement."""
from __future__ import annotations

import ntpath
import os
import threading
from typing import Any, Callable, Generic, Mapping, Sequence, TypeVar

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.native_channel import OwnedChannel
from je_auto_control.utils.process_memory.models import FailureReason, MemoryObservationError
from je_auto_control.utils.process_memory.windows_launch import (
    LaunchRecord, OwnedLaunch, PopenLauncher,
)
from je_auto_control.utils.process_memory.windows_native import ProcessKernel


# What a pinned fixture may inherit: where Windows, the profile and temp live, never the
# host's tokens, keys or a PATH that reaches user-writable directories.
_CHILD_ENVIRONMENT = (
    "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE",
    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "ALLUSERSPROFILE", "PUBLIC", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
    "COMMONPROGRAMW6432", "HOMEDRIVE", "HOMEPATH", "USERNAME", "USERDOMAIN", "COMPUTERNAME", "OS",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL",
    "PROCESSOR_REVISION",
)


def pinned_child_options(path: str, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Start a pinned image in its own (lease-checked) directory with a minimal environment.

    The working directory is on the DLL search path, so it is the image's directory,
    which the lease already proved no other account can write. ``PATH`` holds only
    the system directories.
    """
    source = os.environ if environ is None else environ
    upper = {key.upper(): value for key, value in source.items()}
    env = {key: upper[key] for key in _CHILD_ENVIRONMENT if upper.get(key)}
    root = env.get("SYSTEMROOT")
    if root:
        env["PATH"] = ";".join((ntpath.join(root, "System32"), root, ntpath.join(root, "System32", "Wbem")))
    return {"cwd": ntpath.dirname(path), "env": env}


def pinned_channel(argv: Sequence[str]) -> OwnedChannel:
    """The default memory-fixture channel: the pinned image, never the host's directory or secrets."""
    return OwnedChannel(argv, **pinned_child_options(argv[0]))


def _check_launch(launch: OwnedLaunch, record: LaunchRecord) -> None:
    if not isinstance(launch, OwnedLaunch):
        raise MemoryObservationError(FailureReason.UNSUPPORTED)
    if (launch.record != record
            or (launch.identity.pid, launch.identity.birth) != (record.pid, record.birth)):
        raise MemoryObservationError(FailureReason.TARGET_CHANGED)


ChannelT = TypeVar("ChannelT", bound=OwnedChannel)


class OwnedProcessChannel(Generic[ChannelT]):
    """Adapt pinned-image launch to owned IPC without opening a self-reported PID."""

    def __init__(self, arguments: Sequence[str], *, kernel: ProcessKernel | None = None,
                 last_error: Callable[[], int] | None = None, caller_bits: int | None = None,
                 channel_factory: Callable[[Sequence[str]], ChannelT]) -> None:
        self._factory = channel_factory
        self._channel: ChannelT | None = None
        self._record: LaunchRecord | None = None
        self._terminal = False
        self._lock = threading.Lock()
        self._launcher = PopenLauncher(arguments, kernel=kernel, last_error=last_error,
                                       caller_bits=caller_bits, popen=self._start)

    def _start(self, argv: Sequence[str], *, shell: bool) -> Any:
        if shell or self._terminal or self._channel is not None:
            raise AgentTaskError("fixture launcher requires one owned direct launch")
        self._channel = self._factory(argv)
        if self._terminal:
            self._channel.close()
            raise AgentTaskError("fixture launcher closed during process creation")
        # pylint: disable-next=protected-access  # reason: measure the exact CreateProcess handle retained by this owner
        return self._channel._process

    def __call__(self, path: str) -> LaunchRecord:
        """Launch the leased path once, measuring PID/birth from its retained launch handle."""
        with self._lock:
            if self._terminal or self._record is not None:
                raise AgentTaskError("fixture launcher cannot be reused")
            try:
                self._record = self._launcher(path)
                if self._terminal or self._channel is None or self._channel.retired:
                    raise AgentTaskError("fixture launcher closed during measurement")
                return self._record
            except BaseException as error:
                self._retire_failed(error)
                raise

    def _live_channel(self) -> ChannelT:
        if self._terminal or self._channel is None or self._channel.retired:
            raise AgentTaskError("owned launch has no live channel")
        return self._channel

    def _bound_channel(self, launch: OwnedLaunch) -> ChannelT:
        self._live_channel()
        if self._record is None:
            raise AgentTaskError("owned launch has no measured record")
        _check_launch(launch, self._record)
        if launch.attestor(self._launcher.facts()) != launch.identity:
            raise MemoryObservationError(FailureReason.TARGET_CHANGED)
        return self._live_channel()

    def _retire_failed(self, error: BaseException) -> None:
        try:
            self.close()
        except BaseException as cleanup:
            raise error from cleanup

    def close(self) -> None:
        """Retire only the owned process tree; image leases remain with OwnedLaunch."""
        self._terminal = True
        if self._channel is not None:
            self._channel.close()
            if not self._channel.retired:
                raise AgentTaskError("fixture launch retirement is unconfirmed")
