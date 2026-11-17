"""Closed complete semantic snapshots shared by single-source and reconciled observations."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import sys
from typing import Any, Literal, Mapping

from .errors import AgentTaskError
from .models import detached
from ..process_memory.models import Observation, Scalar

_METADATA = frozenset({"observation_id", "started", "finished"})
_KEYS = frozenset({"target_id", "identity_digest", "adapter_id", "schema_version", "source",
                   "fields", "revision", "consistency", "complete"}) | _METADATA


def _identifier(value: object) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) is None:
        raise AgentTaskError("semantic observation has an invalid identifier")


def _fields(value: Mapping[str, Any]) -> tuple[tuple[str, Scalar], ...]:
    if not isinstance(value, Mapping) or not 1 <= len(value) <= 64:
        raise AgentTaskError("semantic observation requires bounded fields")
    result: list[tuple[str, Scalar]] = []
    for name, item in value.items():
        _identifier(name)
        if isinstance(item, str):
            if len(item.encode("utf-8")) > 65536:
                raise AgentTaskError("semantic field exceeds its byte limit")
        elif isinstance(item, int):
            if not -(2**63) <= item < 2**63:
                raise AgentTaskError("semantic integer exceeds its range")
        elif item is not None:
            raise AgentTaskError("semantic fields must be scalar values")
        result.append((name, item))
    return tuple(sorted(result))


@dataclass(frozen=True, kw_only=True)
# pylint: disable-next=too-many-instance-attributes  # reason: mirrors the closed semantic observation wire schema
class SemanticSnapshot:
    """Complete semantic evidence; freshness metadata is separate from state identity."""

    target_id: str
    identity_digest: str
    adapter_id: str
    schema_version: str
    source: str
    fields: tuple[tuple[str, Scalar], ...] = field(repr=False)
    revision: int | None
    consistency: Literal["sequence_checked", "best_effort"]
    observation_id: str
    started: float
    finished: float
    complete: bool = True

    def __post_init__(self) -> None:
        for value in (self.target_id, self.identity_digest, self.adapter_id, self.schema_version,
                      self.source, self.observation_id):
            _identifier(value)
        if len(dict(self.fields)) != len(self.fields):
            raise AgentTaskError("semantic observation contains duplicate fields")
        object.__setattr__(self, "fields", _fields(dict(self.fields)))
        if self.complete is not True:
            raise AgentTaskError("incomplete semantic observations cannot ground actions")
        self._check_revision()
        for timestamp in (self.started, self.finished):
            if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                    or not 0 <= timestamp <= sys.float_info.max):
                raise AgentTaskError("semantic observation has an invalid capture time")
        if not 0 <= self.started <= self.finished:
            raise AgentTaskError("semantic observation has an invalid capture interval")

    def _check_revision(self) -> None:
        if self.consistency == "best_effort" and self.revision is None:
            return
        if (self.consistency != "sequence_checked" or isinstance(self.revision, bool)
                or not isinstance(self.revision, int) or not 0 <= self.revision < 2**64
                or self.revision % 2):
            raise AgentTaskError("semantic observation has an invalid checked revision")

    @classmethod
    def from_memory(cls, value: Observation) -> SemanticSnapshot:
        """Project a successful reader result without including addresses, handles or raw bytes."""
        return cls(target_id=value.target_id, identity_digest=value.identity_digest,
                   adapter_id=value.probe_id, schema_version=value.schema_version,
                   source=value.source, fields=value.fields, revision=value.revision,
                   consistency=value.consistency, observation_id=value.observation_id,
                   started=value.started, finished=value.finished)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SemanticSnapshot:
        """Validate an exact helper response schema before using it for dispatch."""
        data = detached(value)
        if not isinstance(data, dict) or set(data) != _KEYS:
            raise AgentTaskError("semantic observation has an unknown schema")
        data["fields"] = _fields(data["fields"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """Return bounded semantic fields and their provenance for an authorized caller."""
        return {"target_id": self.target_id, "identity_digest": self.identity_digest,
                "adapter_id": self.adapter_id, "schema_version": self.schema_version,
                "source": self.source, "fields": dict(self.fields), "revision": self.revision,
                "consistency": self.consistency,
                "complete": self.complete, "observation_id": self.observation_id,
                "started": self.started, "finished": self.finished}

    def grounding(self) -> dict[str, Any]:
        """Keep every state and provenance field; omit only validated capture metadata."""
        return {key: value for key, value in self.to_dict().items() if key not in _METADATA}

    def same_state(self, other: SemanticSnapshot) -> bool:
        """Compare state and provenance without Python's boolean/integer coercion."""
        return json.dumps(self.grounding(), sort_keys=True) == json.dumps(other.grounding(), sort_keys=True)
