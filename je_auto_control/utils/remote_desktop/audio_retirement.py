"""One sounddevice stream generation and its admitted operations."""
import threading
from typing import Protocol

from je_auto_control.utils.exception.control_signals import raise_caused_run_interruption

from je_auto_control.utils.remote_desktop.media_retirement import (
    Completion, RetirementStatus,
)


class AudioStream(Protocol):
    """Operations shared by input and output streams."""

    def start(self) -> object: ...
    def stop(self, *, ignore_errors: bool) -> object: ...
    def close(self, *, ignore_errors: bool) -> object: ...


class AudioOutputStream(AudioStream, Protocol):
    """Only output generations support writing PCM."""

    def write(self, data: bytes) -> object: ...


class AudioLease:
    """Keep the exact stream even when sounddevice loses its native pointer."""

    def __init__(self) -> None:
        self.stream: AudioStream | None = None
        self._lock = threading.Lock()
        self._admitting = False
        self._retiring = False
        self._operations = 0
        self._closing = False
        self._close_attempted = False
        self._resources = Completion.PENDING
        self._finalization = Completion.PENDING
        self._failures: tuple[str, ...] = ()

    def activate(self) -> None:
        with self._lock:
            self._admitting = True

    @property
    def running(self) -> bool:
        with self._lock:
            return self._admitting and self.stream is not None

    def enter(self) -> bool:
        with self._lock:
            if not self._admitting:
                return False
            self._operations += 1
            return True

    def leave(self) -> None:
        with self._lock:
            self._operations -= 1

    @property
    def status(self) -> RetirementStatus:
        with self._lock:
            pending = self._retiring and not self._close_attempted
            failures = self._failures
            if pending:
                failures += ("audio.operations_pending",)
            return RetirementStatus(self._retiring, self._resources,
                                    self._finalization, pending, failures)

    def retire(self, *, started: bool = True) -> None:
        with self._lock:
            self._admitting = False
            self._retiring = True
            if self._operations or self._closing or self._close_attempted:
                return
            self._closing = True
        try:
            self._retire_stream(started)
        finally:
            with self._lock:
                self._closing = False

    def _retire_stream(self, started: bool) -> None:
        stream = self.stream
        if stream is None:
            self._resources = Completion.CONFIRMED
            self._finalization = Completion.CONFIRMED
            self._close_attempted = True
            return
        stop_failure = self._stop_stream(stream) if started else None
        if not started:
            self._finalization = Completion.CONFIRMED
        close_failure = self._close_stream(stream)
        for failure in (stop_failure, close_failure):
            if failure is not None:
                raise_caused_run_interruption(failure)

    def _stop_stream(self, stream: AudioStream) -> BaseException | None:
        try:
            stream.stop(ignore_errors=False)
        except BaseException as error:  # reason: close independently before preserving control signals
            self._finalization = Completion.UNCERTAIN
            self._failures += ("audio.stop",)
            return error
        self._finalization = Completion.CONFIRMED
        return None

    def _close_stream(self, stream: AudioStream) -> BaseException | None:
        # sounddevice clears _ptr before checking Pa_CloseStream's result.
        # A repeated close cannot acknowledge the first call's release.
        self._close_attempted = True
        try:
            stream.close(ignore_errors=False)
        except BaseException as error:  # reason: record uncertain ownership before preserving control signals
            self._resources = Completion.UNCERTAIN
            self._failures += ("audio.close",)
            return error
        self._resources = Completion.CONFIRMED
        self.stream = None
        return None
