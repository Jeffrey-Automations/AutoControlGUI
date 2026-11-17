"""Trusted semantic target dispatch with versioned snapshots and stable grounding."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import hashlib
import json
import re
import sys
import time
from typing import Any, Literal, Mapping

from je_auto_control.utils.agent_runtime.errors import AgentTaskError, AgentObservationStale
from je_auto_control.utils.agent_runtime.models import detached, freeze
from je_auto_control.utils.process_memory.models import Observation, Scalar

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


@dataclass(frozen=True)
class SemanticReceipt:
    """A confirmed adapter reply, with the journal ID and explicit comparison guarantee."""

    operation_id: str
    comparison: Literal["atomic", "non_atomic"]
    result: Mapping[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        _identifier(self.operation_id)
        if self.comparison not in {"atomic", "non_atomic"}:
            raise AgentTaskError("semantic receipt requires an explicit comparison guarantee")
        data = detached(self.result)
        if not isinstance(data, dict):
            raise AgentTaskError("semantic receipt requires a structured result")
        object.__setattr__(self, "result", freeze(data))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SemanticReceipt:
        """Reject incomplete or unknown helper receipt formats."""
        data = detached(value)
        if not isinstance(data, dict) or set(data) != {"operation_id", "comparison", "result"}:
            raise AgentTaskError("semantic receipt has an unknown schema")
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """Serialize confirmed values separately from their operation identity and guarantee."""
        return {"operation_id": self.operation_id, "comparison": self.comparison,
                "result": detached(self.result)}


# pylint: disable-next=too-few-public-methods  # reason: nominal opt-in adds grounded dispatch to existing targets
class SemanticTarget(ABC):
    """Host-selected adapter contract, never enabled by a task or observation payload."""

    @abstractmethod
    def perform_grounded(self, name: str, arguments: Mapping[str, Any], *,
                         expected: SemanticSnapshot, operation_id: str) -> SemanticReceipt:
        """Revalidate before commit; use the journal ID to reconcile uncertain effects.

        Atomic adapters compare the revision at commit. Other adapters return a
        non_atomic receipt. An unknown effect raises AgentEffectUnknown instead of
        a receipt. The runtime owns all retries.
        """


def fingerprint(target: Any, observation: Mapping[str, Any]) -> str:
    """Use semantic grounding only for adapters explicitly implementing the host contract."""
    value = (SemanticSnapshot.from_dict(observation).grounding()
             if isinstance(target, SemanticTarget) else detached(observation))
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def observe(target: Any) -> dict[str, Any]:
    """Require a same-host monotonic capture inside this read request before publication."""
    started = time.monotonic()
    value = target.observe()
    finished = time.monotonic()
    if not isinstance(target, SemanticTarget):
        return detached(value)
    snapshot = SemanticSnapshot.from_dict(value)
    if not started <= snapshot.started <= snapshot.finished <= finished:
        raise AgentObservationStale("semantic capture is outside the current read request")
    return snapshot.to_dict()


def grounding_details(target: Any, observation: Mapping[str, Any], observation_id: str) -> dict[str, Any]:
    """Bind semantic completion evidence to the actual host-selected target at dispatch."""
    result: dict[str, Any] = {"observation_id": observation_id, "fingerprint": fingerprint(target, observation)}
    if isinstance(target, SemanticTarget):
        result["semantic"] = SemanticSnapshot.from_dict(observation).to_dict()
    return result


def perform(target: Any, name: str, arguments: Mapping[str, Any], *,
            observation: Mapping[str, Any], operation_id: str) -> Any:
    """Carry expected state and the prepared journal ID to semantic adapters only."""
    if isinstance(target, SemanticTarget):
        expected = SemanticSnapshot.from_dict(observation)
        receipt = target.perform_grounded(
            name, arguments, expected=expected, operation_id=operation_id)
        if not isinstance(receipt, SemanticReceipt) or receipt.operation_id != operation_id:
            raise AgentTaskError("semantic dispatch did not confirm this operation")
        return receipt.to_dict()
    return target.perform(name, arguments)
