"""Closed identities, reviewed probes and safe semantic observation results."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
import re
from typing import Callable, Literal, Mapping, Protocol, TypeAlias

from je_auto_control.utils.exception.exceptions import AutoControlException

Scalar: TypeAlias = str | int | bool | None


class FailureReason(str, Enum):
    UNSUPPORTED = "unsupported"
    SCOPE_DENIED = "scope_denied"
    ACCESS_DENIED = "access_denied"
    TARGET_CHANGED = "target_changed"
    UNREADABLE_REGION = "unreadable_region"
    PARTIAL_READ = "partial_read"
    INCONSISTENT_SNAPSHOT = "inconsistent_snapshot"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    BUDGET_EXCEEDED = "budget_exceeded"
    DECODE_FAILED = "decode_failed"
    CLEANUP_FAILED = "cleanup_failed"


class MemoryObservationError(AutoControlException):
    """A fixed reason; provider details and memory contents never enter its message."""

    def __init__(self, reason: FailureReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


def _identifier(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
        raise MemoryObservationError(FailureReason.UNSUPPORTED)


def _positive(value: int, ceiling: int) -> None:
    if type(value) is not int or not 0 < value <= ceiling:
        raise MemoryObservationError(FailureReason.UNSUPPORTED)


@dataclass(frozen=True)
class ProcessIdentity:
    """Identity measured from the retained process, not from a reusable PID alone."""

    host: str = field(repr=False)
    session: str = field(repr=False)
    pid: int = field(repr=False)
    birth: int = field(repr=False)
    executable: str = field(repr=False)
    version: str = field(repr=False)
    architecture: str
    pointer_bits: int

    def __post_init__(self) -> None:
        for value in (self.host, self.session, self.executable, self.version):
            _identifier(value)
        _positive(self.pid, (1 << 32) - 1)
        _positive(self.birth, (1 << 64) - 1)
        if (type(self.pointer_bits) is not int
                or (self.architecture, self.pointer_bits) not in {("x86", 32), ("x64", 64), ("arm64", 64)}):
            raise MemoryObservationError(FailureReason.UNSUPPORTED)

    @property
    def digest(self) -> str:
        """Bind observations to the measured identity without returning its private fields."""
        value = (self.host, self.session, self.pid, self.birth, self.executable,
                 self.version, self.architecture, self.pointer_bits)
        return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MemoryRegion:
    """Private mapping evidence returned by the provider for an intersecting range."""

    base: int = field(repr=False)
    size: int = field(repr=False)
    allocation: int = field(repr=False)
    protection: int = field(repr=False)
    committed: bool
    readable: bool
    guard: bool


@dataclass(frozen=True)
class ReadPlan:
    """Private locations freshly resolved by a host-reviewed application adapter."""

    address: int = field(repr=False)
    size: int = field(repr=False)
    sequence_address: int | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ReviewedProbe:
    """Immutable host-owned ceiling and trusted version-specific resolver/decoder."""

    probe_id: str
    schema_version: str
    executable: str = field(repr=False)
    versions: tuple[str, ...]
    architectures: tuple[str, ...]
    fields: tuple[str, ...]
    max_bytes: int
    max_regions: int
    timeout: float
    max_value_bytes: int
    resolve: Callable[[ProcessIdentity], ReadPlan] = field(repr=False, compare=False)
    decode: Callable[[bytes, tuple[str, ...]], Mapping[str, Scalar]] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        for value in (self.probe_id, self.schema_version, self.executable):
            _identifier(value)
        for name in ("versions", "architectures", "fields"):
            values = tuple(getattr(self, name))
            if not values or len(values) > 64 or len(set(values)) != len(values):
                raise MemoryObservationError(FailureReason.UNSUPPORTED)
            for value in values:
                _identifier(value)
            object.__setattr__(self, name, values)
        _positive(self.max_bytes, 1 << 20)
        _positive(self.max_regions, 1024)
        _positive(self.max_value_bytes, 65536)
        if (isinstance(self.timeout, bool) or not isinstance(self.timeout, (float, int))
                or not math.isfinite(self.timeout) or not 0 < self.timeout <= 60):
            raise MemoryObservationError(FailureReason.UNSUPPORTED)


class ProcessHandle(Protocol):
    """One retained read-only process handle; close failure leaves ownership with the reader."""

    def identity(self) -> ProcessIdentity: ...

    def query_region(self, address: int) -> MemoryRegion: ...

    def read(self, address: int, size: int) -> bytes: ...

    def close(self) -> None: ...


class ProcessProvider(Protocol):
    """Open only the specified process with read/query rights; no escalation or discovery."""

    def open_readonly(self, identity: ProcessIdentity) -> ProcessHandle: ...


@dataclass(frozen=True)
class Observation:
    observation_id: str
    target_id: str
    identity_digest: str
    probe_id: str
    schema_version: str
    started: float
    finished: float
    fields: tuple[tuple[str, Scalar], ...] = field(repr=False)
    consistency: Literal["sequence_checked", "best_effort"]
    bytes_read: int
    regions_read: int
    source: str = field(default="process_memory", init=False)
    complete: bool = field(default=True, init=False)


@dataclass(frozen=True)
class ObservationFailure:
    reason: FailureReason
    retired: bool = True


ObservationResult: TypeAlias = Observation | ObservationFailure
