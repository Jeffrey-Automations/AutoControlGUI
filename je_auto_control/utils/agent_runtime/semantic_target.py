"""Trusted semantic target dispatch with versioned snapshots and stable grounding."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import hashlib
import json
import time
from typing import Any, ClassVar, Literal, Mapping

from je_auto_control.utils.agent_runtime.errors import AgentTaskError, AgentObservationStale
from je_auto_control.utils.agent_runtime.models import detached, freeze
from .observation_report import ObservationReport
from .semantic_snapshot import SemanticSnapshot, _identifier, _fields

__all__ = ["SemanticSnapshot", "SemanticReceipt", "SemanticTarget", "fingerprint", "observe",
           "grounding_details", "perform", "_identifier", "_fields"]


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


class SemanticTarget(ABC):
    """Host-selected adapter contract, never enabled by a task or observation payload."""

    observation_sources: ClassVar[tuple[str, ...]] = ()

    def perform_observed(self, name: str, arguments: Mapping[str, Any], *,
                         observation: Mapping[str, Any], operation_id: str) -> SemanticReceipt:
        """Validate all required source evidence before converting to the command's primary snapshot."""
        expected = (_report(self, observation).require_grounding() if self.observation_sources
                    else SemanticSnapshot.from_dict(observation))
        return self.perform_grounded(name, arguments, expected=expected, operation_id=operation_id)

    @abstractmethod
    def perform_grounded(self, name: str, arguments: Mapping[str, Any], *,
                         expected: SemanticSnapshot, operation_id: str) -> SemanticReceipt:
        """Revalidate before commit; use the journal ID to reconcile uncertain effects.

        Atomic adapters compare the revision at commit. Other adapters return a
        non_atomic receipt. An unknown effect raises AgentEffectUnknown instead of
        a receipt. The runtime owns all retries.
        """

    @abstractmethod
    def cleanup(self) -> None:
        """Retire owned resources; raise and retain ownership when cleanup needs a retry."""


def fingerprint(target: Any, observation: Mapping[str, Any]) -> str:
    """Use semantic grounding only for adapters explicitly implementing the host contract."""
    if isinstance(target, SemanticTarget) and target.observation_sources:
        value = _report(target, observation).grounding()
    else:
        value = (SemanticSnapshot.from_dict(observation).grounding()
                 if isinstance(target, SemanticTarget) else detached(observation))
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def _report(target: SemanticTarget, observation: Mapping[str, Any]) -> ObservationReport:
    return ObservationReport.from_dict(observation, required=target.observation_sources)


def observe(target: Any) -> dict[str, Any]:
    """Require a same-host monotonic capture inside this read request before publication."""
    started = time.monotonic()
    value = target.observe()
    finished = time.monotonic()
    if not isinstance(target, SemanticTarget):
        return detached(value)
    snapshot = _report(target, value) if target.observation_sources else SemanticSnapshot.from_dict(value)
    if not started <= snapshot.started <= snapshot.finished <= finished:
        raise AgentObservationStale("semantic capture is outside the current read request")
    return snapshot.to_dict()


def grounding_details(target: Any, observation: Mapping[str, Any], observation_id: str) -> dict[str, Any]:
    """Bind semantic completion evidence to the actual host-selected target at dispatch."""
    result: dict[str, Any] = {"observation_id": observation_id, "fingerprint": fingerprint(target, observation)}
    if isinstance(target, SemanticTarget):
        if target.observation_sources:
            report = _report(target, observation)
            result["semantic_report"] = report.to_dict()
            result["semantic_sources"] = list(target.observation_sources)
            result["semantic"] = report.require_grounding().to_dict()
        else:
            result["semantic"] = SemanticSnapshot.from_dict(observation).to_dict()
    return result


def perform(target: Any, name: str, arguments: Mapping[str, Any], *,
            observation: Mapping[str, Any], operation_id: str) -> Any:
    """Carry expected state and the prepared journal ID to semantic adapters only."""
    if isinstance(target, SemanticTarget):
        receipt = target.perform_observed(
            name, arguments, observation=observation, operation_id=operation_id)
        if not isinstance(receipt, SemanticReceipt) or receipt.operation_id != operation_id:
            raise AgentTaskError("semantic dispatch did not confirm this operation")
        return receipt.to_dict()
    return target.perform(name, arguments)
