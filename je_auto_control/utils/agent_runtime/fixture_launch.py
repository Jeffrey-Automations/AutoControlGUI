"""Measure an owned fixture channel's launch handle before binding its private bootstrap."""
from __future__ import annotations

from typing import Callable, Sequence

from .errors import AgentTaskError
from .fixture_control import OwnedFixtureControl
from .native_channel import OwnedChannel
from .owned_channel_launch import OwnedProcessChannel, pinned_channel
from ..process_memory.models import FailureReason, MemoryObservationError
from ..process_memory.windows_launch import OwnedLaunch
from ..process_memory.windows_native import ProcessKernel


class OwnedChannelLauncher(OwnedProcessChannel[OwnedChannel]):
    """Bind only the attested launch's fixed memory-fixture RPC bootstrap."""

    def __init__(self, arguments: Sequence[str], *, kernel: ProcessKernel | None = None,
                 last_error: Callable[[], int] | None = None, caller_bits: int | None = None,
                 channel_factory: Callable[[Sequence[str]], OwnedChannel] = pinned_channel) -> None:
        self._control: OwnedFixtureControl | None = None
        super().__init__(arguments, kernel=kernel, last_error=last_error, caller_bits=caller_bits,
                         channel_factory=channel_factory)

    def bind_control(self, launch: OwnedLaunch, challenge: bytes, *,
                     checkpoint: Callable[[], None]) -> OwnedFixtureControl:
        """Refuse descendant or mismatched bootstrap PIDs; image attestation remains separate."""
        with self._lock:
            if (self._terminal or self._channel is None
                    or self._record is None or self._control is not None):
                raise AgentTaskError("fixture launcher has no unbound live channel")
            try:
                self._bound_channel(launch)
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

    def close(self) -> None:
        """Invalidate the bound protocol before retiring the shared process owner."""
        self._terminal = True
        if self._control is not None:
            self._control.close()
        super().close()
