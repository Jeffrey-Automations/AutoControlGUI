"""Adapter-owned semantic observations with bounded reads and retained cleanup ownership."""
from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Callable, Mapping, TypeVar
from uuid import uuid4

from je_auto_control.utils.exception.cancellation import cancellation_checkpoint
from je_auto_control.utils.exception.control_signals import raise_if_run_interrupted
from je_auto_control.utils.executor.run_control import ExecutionStopped
from je_auto_control.utils.process_memory.models import (
    FailureReason, MemoryObservationError, MemoryRegion, Observation, ObservationFailure,
    ObservationResult, ProcessHandle, ProcessIdentity, ProcessProvider, ReadPlan, ReviewedProbe, Scalar,
    _identifier,
)

_T = TypeVar("_T")


class _ObservationFailed(MemoryObservationError):
    """Only reader-owned failures are converted to results; authority callbacks are not."""


def _preserve_interruption(error: BaseException) -> None:
    if isinstance(error, ExecutionStopped):
        raise error
    raise_if_run_interrupted(error)


def _provider_call(call: Callable[[], _T]) -> _T:
    try:
        return call()
    except Exception as error:  # reason: sanitize provider detail, preserving interruption signals
        _preserve_interruption(error)
        reason = FailureReason.TARGET_CHANGED
        if isinstance(error, PermissionError):
            reason = FailureReason.ACCESS_DENIED
        elif isinstance(error, MemoryObservationError) and isinstance(error.reason, FailureReason):
            reason = error.reason
        raise _ObservationFailed(reason) from None


def _fail(reason: FailureReason) -> None:
    raise _ObservationFailed(reason)


def _range(address: int, size: int, bits: int) -> None:
    if (type(address) is not int or type(size) is not int or address < 0 or size <= 0
            or address >= 1 << bits or size > (1 << bits) - address):
        _fail(FailureReason.UNREADABLE_REGION)


@dataclass
class _Operation:
    expected: ProcessIdentity
    probe: ReviewedProbe
    checkpoint: Callable[[], None]
    clock: Callable[[], float]
    deadline: float
    bytes_read: int = 0
    regions_read: int = 0

    def check(self) -> None:
        self.checkpoint()
        if self.clock() >= self.deadline:
            _fail(FailureReason.DEADLINE_EXCEEDED)

    def identity(self, handle: ProcessHandle) -> None:
        self.check()
        if _provider_call(handle.identity) != self.expected:
            _fail(FailureReason.TARGET_CHANGED)
        self.check()

    def region(self, handle: ProcessHandle, address: int) -> MemoryRegion:
        self.check()
        value = _provider_call(lambda: handle.query_region(address))
        self.check()
        if not isinstance(value, MemoryRegion):
            _fail(FailureReason.UNREADABLE_REGION)
        _range(value.base, value.size, self.expected.pointer_bits)
        if (any(type(flag) is not bool for flag in (value.committed, value.readable, value.guard))
                or type(value.allocation) is not int or not 0 <= value.allocation < 1 << self.expected.pointer_bits
                or type(value.protection) is not int or not 0 <= value.protection < 1 << 32
                or not value.base <= address < value.base + value.size or not value.committed
                or not value.readable or value.guard):
            _fail(FailureReason.UNREADABLE_REGION)
        return value

    def read(self, handle: ProcessHandle, address: int, size: int) -> bytes:
        _range(address, size, self.expected.pointer_bits)
        if size > self.probe.max_bytes - self.bytes_read:
            _fail(FailureReason.BUDGET_EXCEEDED)
        collected = bytearray()
        while len(collected) < size:
            self.identity(handle)
            if self.regions_read >= self.probe.max_regions:
                _fail(FailureReason.BUDGET_EXCEEDED)
            current = address + len(collected)
            region = self.region(handle, current)
            count = min(size - len(collected), region.base + region.size - current)
            self.bytes_read += count
            self.regions_read += 1
            chunk = _provider_call(lambda: handle.read(current, count))
            self.check()
            if type(chunk) is not bytes or len(chunk) != count:
                _fail(FailureReason.PARTIAL_READ)
            if self.region(handle, current) != region:
                _fail(FailureReason.TARGET_CHANGED)
            self.identity(handle)
            collected.extend(chunk)
        return bytes(collected)


def _values(decoded: Mapping[str, Scalar], fields: tuple[str, ...], limit: int) -> tuple[tuple[str, Scalar], ...]:
    if set(decoded) != set(fields):
        _fail(FailureReason.DECODE_FAILED)
    values: list[tuple[str, Scalar]] = []
    for name in fields:
        value = decoded[name]
        if type(value) is str:
            if len(value.encode("utf-8")) > limit:
                _fail(FailureReason.DECODE_FAILED)
        elif type(value) is int:
            if not -(1 << 63) <= value < 1 << 63:
                _fail(FailureReason.DECODE_FAILED)
        elif value is not None and type(value) is not bool:
            _fail(FailureReason.DECODE_FAILED)
        values.append((name, value))
    return tuple(values)


class ProcessMemoryReader:
    """Run reviewed queries; failed closes remain owned until an explicit cleanup retry."""

    def __init__(self, provider: ProcessProvider, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._provider = provider
        self._clock = clock
        self._pending: list[ProcessHandle] = []
        self._cleanup_inflight = 0
        self._cleanup_lock = threading.Lock()

    @property
    def pending_cleanup(self) -> bool:
        with self._cleanup_lock:
            return bool(self._pending or self._cleanup_inflight)

    def _close(self, handle: ProcessHandle) -> bool:
        try:
            handle.close()
        except BaseException as error:  # reason: retain failed ownership even when cleanup is interrupted
            with self._cleanup_lock:
                self._pending.append(handle)
            _preserve_interruption(error)
            if not isinstance(error, Exception):
                raise
            return False
        return True

    def close_pending(self) -> bool:
        """Retry only retained failed handles; simultaneous readers keep their own live handles."""
        with self._cleanup_lock:
            pending, self._pending = self._pending, []
            self._cleanup_inflight += len(pending)
        success = True
        try:
            for index, handle in enumerate(pending):
                try:
                    success = self._close(handle) and success
                except BaseException:  # reason: retain remaining handles before propagating interruption
                    with self._cleanup_lock:
                        self._pending.extend(pending[index + 1:])
                    raise
        finally:
            with self._cleanup_lock:
                self._cleanup_inflight -= len(pending)
        return success and not self.pending_cleanup

    def observe(self, expected: ProcessIdentity, probe: ReviewedProbe, fields: tuple[str, ...], *,
                target_id: str, checkpoint: Callable[[], None] = cancellation_checkpoint) -> ObservationResult:
        """Query semantic fields under a host-reviewed probe and the runtime's live checkpoint."""
        selected = tuple(fields)
        if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(probe.fields):
            return ObservationFailure(FailureReason.SCOPE_DENIED)
        _identifier(target_id)
        if (expected.executable != probe.executable or expected.version not in probe.versions
                or expected.architecture not in probe.architectures):
            return ObservationFailure(FailureReason.UNSUPPORTED)
        started = self._clock()
        operation = _Operation(expected, probe, checkpoint, self._clock, started + probe.timeout)
        handle: ProcessHandle | None = None
        retired = True
        result: ObservationResult
        try:
            operation.check()
            handle = _provider_call(lambda: self._provider.open_readonly(expected))
            result = self._collect(handle, operation, selected, target_id, started)
        except _ObservationFailed as error:
            result = ObservationFailure(error.reason)
        finally:
            if handle is not None:
                retired = self._close(handle)
        if not retired:
            return ObservationFailure(FailureReason.CLEANUP_FAILED, retired=False)
        if isinstance(result, Observation):
            try:
                operation.check()
            except _ObservationFailed as error:
                return ObservationFailure(error.reason)
        return result

    def _collect(self, handle: ProcessHandle, operation: _Operation, fields: tuple[str, ...],
                 target_id: str, started: float) -> Observation:
        operation.identity(handle)
        probe = operation.probe
        try:
            plan = probe.resolve(operation.expected)
        except Exception as error:  # reason: resolver failures must not disclose private addresses
            _preserve_interruption(error)
            raise _ObservationFailed(FailureReason.UNSUPPORTED) from None
        if not isinstance(plan, ReadPlan):
            _fail(FailureReason.UNSUPPORTED)
        operation.check()
        before: bytes | None = None
        if plan.sequence_address is not None:
            before = operation.read(handle, plan.sequence_address, 8)
            if int.from_bytes(before, "little") % 2:
                _fail(FailureReason.INCONSISTENT_SNAPSHOT)
        raw = operation.read(handle, plan.address, plan.size)
        if plan.sequence_address is not None:
            if operation.read(handle, plan.sequence_address, 8) != before:
                _fail(FailureReason.INCONSISTENT_SNAPSHOT)
        try:
            values = _values(probe.decode(raw, fields), fields, probe.max_value_bytes)
        except Exception as error:  # reason: decoder failures must not disclose captured bytes
            _preserve_interruption(error)
            raise _ObservationFailed(FailureReason.DECODE_FAILED) from None
        operation.check()
        operation.identity(handle)
        return Observation(uuid4().hex, target_id, operation.expected.digest, probe.probe_id, probe.schema_version,
                           started, operation.clock(), values,
                           "sequence_checked" if before is not None else "best_effort",
                           operation.bytes_read, operation.regions_read)
