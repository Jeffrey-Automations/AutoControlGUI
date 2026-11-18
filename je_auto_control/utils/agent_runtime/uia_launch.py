"""Bind a private UI-fixture HWND to the independently attested retained launch."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from .errors import AgentTaskError
from .owned_channel_launch import OwnedProcessChannel, pinned_child_options
from .uia_channel import OwnedUiaChannel
from ..process_memory.models import FailureReason, MemoryObservationError, ProcessIdentity
from ..process_memory.windows_launch import OwnedLaunch
from ..process_memory.windows_native import ProcessKernel
from ..process_memory.windows_window import WindowOwnerQuery


@dataclass(frozen=True)
class BoundUiaWindow:
    """Non-owning private binding; verify before and after using the HWND in the owning helper."""

    identity: ProcessIdentity
    hwnd: int = field(repr=False)
    _verify: Callable[[Callable[[], None]], None] = field(repr=False)

    def verify(self, checkpoint: Callable[[], None]) -> None:
        """Revalidate the original process and current window owner without minting a new identity."""
        self._verify(checkpoint)


def pinned_uia_channel(argv: Sequence[str]) -> OwnedUiaChannel:
    """The default UI-fixture channel: the pinned image, never the host's directory or secrets."""
    return OwnedUiaChannel(argv, **pinned_child_options(argv[0]))


class OwnedUiaLauncher(OwnedProcessChannel[OwnedUiaChannel]):
    """Own only the pinned fixture; bootstrap PID and HWND never select a process to open."""

    def __init__(self, challenge: bytes, *, windows: WindowOwnerQuery,
                 kernel: ProcessKernel | None = None, last_error: Callable[[], int] | None = None,
                 caller_bits: int | None = None,
                 channel_factory: Callable[[Sequence[str]], OwnedUiaChannel] = pinned_uia_channel) -> None:
        if type(challenge) is not bytes or len(challenge) != 16:
            raise AgentTaskError("UI fixture requires a 16-byte challenge")
        self._challenge, self._windows = challenge, windows
        self._binding: BoundUiaWindow | None = None
        super().__init__(("--challenge", challenge.hex()), kernel=kernel, last_error=last_error,
                         caller_bits=caller_bits, channel_factory=channel_factory)

    def bind_window(self, launch: OwnedLaunch, *, checkpoint: Callable[[], None]) -> BoundUiaWindow:
        """Consume one startup and require independent measurements before publishing its HWND."""
        with self._lock:
            if self._binding is not None:
                raise AgentTaskError("UI fixture window is already bound")
            try:
                checkpoint()
                channel = self._bound_channel(launch)
                value = channel.bootstrap(self._challenge, timeout=5, check=checkpoint)
                hwnd = self._bootstrap_window(value, launch.identity)
                self._verify_window(launch, hwnd, checkpoint)
                self._binding = BoundUiaWindow(launch.identity, hwnd,
                    lambda check: self._verify_window(launch, hwnd, check))
                return self._binding
            except BaseException as error:
                self._retire_failed(error)
                raise

    def _bootstrap_window(self, value: object, identity: ProcessIdentity) -> int:
        if not isinstance(value, dict) or set(value) != {"fixture", "version", "pid", "hwnd", "challenge"}:
            raise AgentTaskError("UI fixture startup has an unknown schema")
        if (type(value["version"]) is not int
                or (value["fixture"], value["version"], value["challenge"]) != ("uia", 1, self._challenge.hex())):
            raise AgentTaskError("UI fixture startup does not match its launch")
        if (type(value["pid"]) is not int or value["pid"] != identity.pid
                or type(value["hwnd"]) is not int or not 0 < value["hwnd"] < 2**identity.pointer_bits):
            raise MemoryObservationError(FailureReason.TARGET_CHANGED)
        return value["hwnd"]

    def _verify_window(self, launch: OwnedLaunch, hwnd: int, checkpoint: Callable[[], None]) -> None:
        try:
            for _ in range(2):
                checkpoint()
                self._bound_channel(launch).check_live()
                if self._windows.process_id(hwnd) != launch.identity.pid:
                    raise MemoryObservationError(FailureReason.TARGET_CHANGED)
            self._bound_channel(launch).check_live()
            checkpoint()
            self._live_channel().check_live()
        except BaseException as error:
            self._retire_failed(error)
            raise
