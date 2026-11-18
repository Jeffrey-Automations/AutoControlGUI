"""Version-one fixture decoding and challenge-bound resolution for reviewed launches."""
from __future__ import annotations

from dataclasses import dataclass, field
import hmac
import struct
from typing import Mapping

from je_auto_control.utils.process_memory.models import (
    FailureReason, MemoryObservationError, ProcessIdentity, ReadPlan, ResolverView,
    ReviewedProbe, Scalar, _positive,
)

_HEADER = struct.Struct("<8s16sQQ")
_PAYLOAD = struct.Struct("<I12s")
_FIELDS = ("document_id", "job_status")


def _integer(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise MemoryObservationError(FailureReason.UNSUPPORTED)
    return value


def decode_fixture(raw: bytes, fields: tuple[str, ...]) -> Mapping[str, Scalar]:
    """Decode exact schema-one bytes, rejecting unknown states and noncanonical padding."""
    if (not isinstance(raw, bytes) or len(raw) != _PAYLOAD.size or not fields
            or len(set(fields)) != len(fields) or not set(fields) <= set(_FIELDS)):
        raise MemoryObservationError(FailureReason.DECODE_FAILED)
    document_id, encoded = _PAYLOAD.unpack(raw)
    states = {name.encode("ascii").ljust(12, b"\0"): name for name in ("ready", "busy", "done")}
    if encoded not in states:
        raise MemoryObservationError(FailureReason.DECODE_FAILED)
    values: dict[str, Scalar] = {"document_id": document_id, "job_status": states[encoded]}
    return {name: values[name] for name in fields}


@dataclass(frozen=True)
class FixtureBinding:
    """Private launch locations; validation does not confer executable trust or authority."""

    pid: int = field(repr=False)
    pointer_bits: int
    header: int = field(repr=False)
    payload: int = field(repr=False)
    sequence: int = field(repr=False)
    challenge: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _positive(self.pid, 2**32 - 1)
        _positive(self.pointer_bits, 64)
        if self.pointer_bits not in (32, 64):
            raise MemoryObservationError(FailureReason.UNSUPPORTED)
        if (not isinstance(self.challenge, bytes) or len(self.challenge) != 16
                or not any(self.challenge)):
            raise MemoryObservationError(FailureReason.UNSUPPORTED)
        ranges = ((self.header, _HEADER.size), (self.payload, _PAYLOAD.size), (self.sequence, 8))
        for address, size in ranges:
            _positive(address, 2**self.pointer_bits - size)
        ordered = sorted(ranges)
        if any(start + size > following
               for (start, size), (following, _) in zip(ordered, ordered[1:])):
            raise MemoryObservationError(FailureReason.UNSUPPORTED)

    @classmethod
    def from_bootstrap(cls, challenge: bytes, bootstrap: Mapping[str, object]) -> FixtureBinding:
        """Require the supported protocol and layout before accepting untrusted locations."""
        required = {"kind": "bootstrap", "protocol_version": 1, "schema_version": 1,
                    "identity": "self_reported", "header_size": 40,
                    "payload_size": 16, "sequence_size": 8}
        if any(type(bootstrap.get(key)) is not type(value) or bootstrap.get(key) != value
               for key, value in required.items()):
            raise MemoryObservationError(FailureReason.UNSUPPORTED)
        return cls(_integer(bootstrap, "pid"), _integer(bootstrap, "pointer_bits"),
                   _integer(bootstrap, "header_address"), _integer(bootstrap, "payload_address"),
                   _integer(bootstrap, "sequence_address"), challenge)

    def resolve(self, identity: ProcessIdentity, view: ResolverView) -> ReadPlan:
        """Re-read the launch header through the reader's bounded retained-handle view."""
        if identity.pid != self.pid or identity.pointer_bits != self.pointer_bits:
            raise MemoryObservationError(FailureReason.TARGET_CHANGED)
        magic, challenge, payload, sequence = _HEADER.unpack(view.read(self.header, _HEADER.size))
        if (magic != b"JEPMFIX1" or not hmac.compare_digest(challenge, self.challenge)
                or (payload, sequence) != (self.payload, self.sequence)):
            raise MemoryObservationError(FailureReason.UNSUPPORTED)
        return ReadPlan(payload, _PAYLOAD.size, sequence)

    def probe(self, executable: str) -> ReviewedProbe:
        """Bind schema one to a separately attested executable and version one."""
        return ReviewedProbe("fixture-document", "1", executable, ("1",), ("x86", "x64", "arm64"),
                             _FIELDS, 72, 8, 1.0, 32, self.resolve, decode_fixture)
