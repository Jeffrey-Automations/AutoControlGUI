"""Keep successful scalar fields and explicit per-field failures without action authority."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .capture_metadata import CaptureMetadata, _identifier
from .errors import AgentTaskError
from .models import detached
from .semantic_snapshot import _fields
from ..process_memory.models import Scalar

FIELD_FAILURES = frozenset({"not_found", "ambiguous", "protected", "unsupported", "unreadable", "budget_exceeded"})


@dataclass(frozen=True)
class PartialObservation:
    """A partial source is diagnostic even when its successful fields agree with another source."""

    capture: CaptureMetadata
    fields: tuple[tuple[str, Scalar], ...] = field(repr=False)
    failures: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.capture, CaptureMetadata):
            raise AgentTaskError("partial observation requires validated capture metadata")
        fields, failures = tuple(self.fields), _failure_fields(tuple(self.failures))
        if len(dict(fields)) != len(fields):
            raise AgentTaskError("partial observation contains duplicate fields")
        if len(fields) + len(failures) > 64 or set(dict(fields)) & set(dict(failures)):
            raise AgentTaskError("partial observation requires disjoint bounded values and failures")
        object.__setattr__(self, "fields", _fields(dict(fields)) if fields else ())
        object.__setattr__(self, "failures", tuple(sorted(failures)))

    def to_dict(self) -> dict[str, Any]:
        """Publish fixed reasons separately from legitimate empty, false or null values."""
        return {"capture": self.capture.to_dict(), "fields": dict(self.fields), "failures": dict(self.failures)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PartialObservation:
        """Validate the closed partial-source schema before reporting its known fields."""
        data = detached(value)
        if (not isinstance(data, dict) or set(data) != {"capture", "fields", "failures"}
                or not isinstance(data["fields"], dict) or not isinstance(data["failures"], dict)):
            raise AgentTaskError("partial observation has an unknown schema")
        return cls(CaptureMetadata.from_dict(data["capture"]), tuple(data["fields"].items()),
                   tuple(data["failures"].items()))


def _failure_fields(failures: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    if not 1 <= len(failures) <= 64 or len(dict(failures)) != len(failures):
        raise AgentTaskError("partial observation requires unique bounded field failures")
    for name, reason in failures:
        _identifier(name)
        if not isinstance(reason, str) or reason not in FIELD_FAILURES:
            raise AgentTaskError("partial observation has an invalid field failure")
    return tuple(sorted(failures))
