"""Measure an owned fixture channel's launch handle before binding its private bootstrap."""
from __future__ import annotations

import threading
from typing import Any, Callable, Sequence

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.fixture_control import OwnedFixtureControl
from je_auto_control.utils.agent_runtime.native_channel import OwnedChannel
from je_auto_control.utils.process_memory.models import FailureReason, MemoryObservationError
from je_auto_control.utils.process_memory.windows_launch import (
    LaunchRecord, OwnedLaunch, PopenLauncher,
)
from je_auto_control.utils.process_memory.windows_native import ProcessKernel


def _check_launch(launch: OwnedLaunch, record: LaunchRecord) -> None:
    if not isinstance(launch, OwnedLaunch):
        raise MemoryObservationError(FailureReason.UNSUPPORTED)
    if (launch.record != record
            or (launch.identity.pid, launch.identity.birth) != (record.pid, record.birth)):
        raise MemoryObservationError(FailureReason.TARGET_CHANGED)


class OwnedChannelLauncher:
    """Adapt pinned-image launch to owned IPC without opening a self-reported PID."""

    def __init__(self, arguments: Sequence[str], *, kernel: ProcessKernel | None = None,
                 last_error: Callable[[], int] | None = None, caller_bits: int | None = None,
                 channel_factory: Callable[[Sequence[str]], OwnedChannel] = OwnedChannel) -> None:
        self._factory = channel_factory
        self._channel: OwnedChannel | None = None
        self._record: LaunchRecord | None = None
        self._control: OwnedFixtureControl | None = None
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

    def bind_control(self, launch: OwnedLaunch, challenge: bytes, *,
                     checkpoint: Callable[[], None]) -> OwnedFixtureControl:
        """Refuse descendant or mismatched bootstrap PIDs; image attestation remains separate."""
        with self._lock:
            if (self._terminal or self._channel is None
                    or self._record is None or self._control is not None):
                raise AgentTaskError("fixture launcher has no unbound live channel")
            try:
                _check_launch(launch, self._record)
                self._control = OwnedFixtureControl(self._channel, challenge)
                session = self._control.bootstrap(timeout=1, checkpoint=checkpoint)
                if ((session.binding.pid, session.binding.pointer_bits)
                        != (launch.identity.pid, launch.identity.pointer_bits)):
                    raise MemoryObservationError(FailureReason.TARGET_CHANGED)
                checkpoint()
                if self._terminal or self._channel.retired:
                    raise AgentTaskError("fixture launcher retired during binding")
                return self._control
            except BaseException as error:
                self._retire_failed(error)
                raise

    def _retire_failed(self, error: BaseException) -> None:
        try:
            self.close()
        except BaseException as cleanup:
            raise error from cleanup

    def close(self) -> None:
        """Retire only the owned process tree; image leases remain with OwnedLaunch."""
        self._terminal = True
        if self._channel is not None:
            if self._control is not None:
                self._control.close()
            else:
                self._channel.close()
            if not self._channel.retired:
                raise AgentTaskError("fixture launch retirement is unconfirmed")
