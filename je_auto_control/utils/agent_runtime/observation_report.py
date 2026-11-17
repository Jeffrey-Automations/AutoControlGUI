"""Preserve bounded source disagreement without granting incomplete observations action authority."""
from __future__ import annotations

from dataclasses import dataclass, field
import sys
from typing import Any, Mapping

from .errors import AgentObservationStale, AgentTaskError
from .models import detached
from .semantic_snapshot import SemanticSnapshot, _identifier

_FAILURES = frozenset({"unsupported", "access_denied", "unreadable_region", "partial_read",
                       "inconsistent_snapshot", "deadline_exceeded", "budget_exceeded", "decode_failed"})


def _interval(started: float, finished: float) -> None:
    for stamp in (started, finished):
        if type(stamp) not in (int, float) or not 0 <= stamp <= sys.float_info.max:
            raise AgentTaskError("observation report has an invalid capture interval")
    if started > finished:
        raise AgentTaskError("observation report has an invalid capture interval")


def _disagrees(values: list[Any]) -> bool:
    return any(type(item) is not type(values[0]) or item != values[0] for item in values)


@dataclass(frozen=True)
class ObservationReport:
    """An immutable capture envelope; source failures retain no exception text or raw bytes."""

    primary: str
    sources: tuple[tuple[str, SemanticSnapshot | str], ...] = field(repr=False)
    started: float
    finished: float

    def __post_init__(self) -> None:
        _identifier(self.primary)
        sources = tuple(self.sources)
        if not 1 <= len(sources) <= 4 or len(dict(sources)) != len(sources):
            raise AgentTaskError("observation report requires unique bounded sources")
        if self.primary not in dict(sources):
            raise AgentTaskError("observation report has no primary source")
        _interval(self.started, self.finished)
        for name, value in sources:
            _identifier(name)
            self._check_source(name, value)
        object.__setattr__(self, "sources", tuple(sorted(sources)))
        successes = [value for _, value in sources if isinstance(value, SemanticSnapshot)]
        if successes and any((item.target_id, item.identity_digest) !=
                             (successes[0].target_id, successes[0].identity_digest) for item in successes):
            raise AgentObservationStale("observation sources belong to different target lifetimes")

    def _check_source(self, name: str, value: SemanticSnapshot | str) -> None:
        if isinstance(value, SemanticSnapshot):
            if value.source != name or not self.started <= value.started <= value.finished <= self.finished:
                raise AgentTaskError("observation source is outside its capture envelope")
        elif not isinstance(value, str) or value not in _FAILURES:
            raise AgentTaskError("observation source failure is invalid")

    def _differences(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        grouped: dict[str, list[Any]] = {}
        for _, value in self.sources:
            if isinstance(value, SemanticSnapshot):
                for name, item in value.fields:
                    grouped.setdefault(name, []).append(item)
        missing, conflicts = set(), set()
        for name, present in grouped.items():
            if len(present) != len(self.sources):
                missing.add(name)
            if _disagrees(present):
                conflicts.add(name)
        return tuple(sorted(missing)), tuple(sorted(conflicts))

    @property
    def status(self) -> str:
        """Derive readiness from every source, typed field comparison and checked revisions."""
        missing, conflicts = self._differences()
        values = [value for _, value in self.sources if isinstance(value, SemanticSnapshot)]
        if conflicts or len({value.revision for value in values}) > 1:
            return "conflict"
        if missing or len(values) != len(self.sources):
            return "partial"
        if any(value.revision is None for value in values):
            return "unverified"
        return "complete"

    def require_grounding(self) -> SemanticSnapshot:
        """Only concordant complete sources may supply the primary action snapshot."""
        if self.status != "complete":
            raise AgentObservationStale("observation sources do not establish complete consistent state")
        primary = dict(self.sources)[self.primary]
        if not isinstance(primary, SemanticSnapshot):
            raise AgentObservationStale("observation primary source is unavailable")
        return primary

    def grounding(self) -> dict[str, Any]:
        """Retain all source state and provenance; omit only capture identifiers and times."""
        self.require_grounding()
        return {"report_version": 1, "primary": self.primary,
                "sources": {name: value.grounding() for name, value in self.sources
                            if isinstance(value, SemanticSnapshot)}}

    def to_dict(self) -> dict[str, Any]:
        """Publish bounded source diagnostics without converting failures into values."""
        missing, conflicts = self._differences()
        return {"report_version": 1, "primary": self.primary, "started": self.started, "finished": self.finished,
                "sources": {name: {"snapshot": value.to_dict()} if isinstance(value, SemanticSnapshot)
                            else {"failure": value} for name, value in self.sources},
                "status": self.status, "missing_fields": list(missing), "conflicting_fields": list(conflicts)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, required: tuple[str, ...]) -> ObservationReport:
        """Validate the closed wire schema against the host's ordered source contract."""
        data = detached(value)
        keys = {"report_version", "primary", "started", "finished", "sources", "status",
                "missing_fields", "conflicting_fields"}
        if not isinstance(data, dict) or set(data) != keys or type(data["report_version"]) is not int:
            raise AgentTaskError("observation report has an unknown schema")
        _source_contract(data, required)
        sources = tuple((name, _source(item)) for name, item in data["sources"].items())
        report = cls(data["primary"], sources, data["started"], data["finished"])
        if report.to_dict() != data:
            raise AgentTaskError("observation report summary does not match its sources")
        return report


def _source_contract(data: dict[str, Any], required: tuple[str, ...]) -> None:
    if (data["report_version"] != 1 or not required or data["primary"] != required[0]
            or not isinstance(data["sources"], dict) or set(data["sources"]) != set(required)):
        raise AgentTaskError("observation report does not match the host source contract")


def _source(value: Any) -> SemanticSnapshot | str:
    if isinstance(value, dict) and set(value) == {"snapshot"}:
        return SemanticSnapshot.from_dict(value["snapshot"])
    if isinstance(value, dict) and set(value) == {"failure"} and isinstance(value["failure"], str):
        return value["failure"]
    raise AgentTaskError("observation source has an unknown schema")
