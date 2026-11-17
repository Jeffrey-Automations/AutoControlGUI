"""Dispatch explicit service evidence separately from existing semantic and ordinary targets."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Mapping

from .errors import AgentEffectUnknown, AgentObservationStale
from . import semantic_target
from .service_observation import SERVICE_TOOLS, ServiceObservation, ServiceReceipt
from .service_target import ServiceTarget


def fingerprint(target: Any, observation: Mapping[str, Any]) -> str:
    """Exclude service capture metadata without weakening semantic source requirements."""
    if not isinstance(target, ServiceTarget):
        return semantic_target.fingerprint(target, observation)
    value = ServiceObservation.from_dict(observation).grounding()
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def observe(target: Any) -> dict[str, Any]:
    """Require service captures to be contained in the current host read request."""
    if not isinstance(target, ServiceTarget):
        return semantic_target.observe(target)
    started = time.monotonic()
    value = ServiceObservation.from_dict(target.observe())
    finished = time.monotonic()
    if not started <= value.started <= value.finished <= finished:
        raise AgentObservationStale("service capture is outside the current read request")
    return value.to_dict()


def grounding_details(target: Any, observation: Mapping[str, Any], observation_id: str) -> dict[str, Any]:
    """Pin service command evidence to the actual host-selected source contract."""
    if not isinstance(target, ServiceTarget):
        return semantic_target.grounding_details(target, observation, observation_id)
    return {"observation_id": observation_id, "fingerprint": fingerprint(target, observation),
            "service": ServiceObservation.from_dict(observation).to_dict()}


def perform(target: Any, name: str, arguments: Mapping[str, Any], *,
            observation: Mapping[str, Any], operation_id: str) -> Any:
    """Validate only service acceptance; completion requires a later independent query."""
    if not isinstance(target, ServiceTarget):
        return semantic_target.perform(target, name, arguments, observation=observation, operation_id=operation_id)
    before = ServiceObservation.from_dict(observation)
    receipt = target.perform_observed(name, arguments, observation=observation, operation_id=operation_id)
    finished = time.monotonic()
    if (type(receipt) is not ServiceReceipt or receipt.operation_id != operation_id
            or receipt.binding != before.binding or receipt.operation is not SERVICE_TOOLS.get(name)
            or not before.finished <= receipt.accepted_at <= finished):
        raise AgentEffectUnknown("service dispatch did not confirm this operation")
    return receipt.to_dict()
