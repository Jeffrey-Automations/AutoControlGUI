"""Verify a post-acceptance SCM report without inferring atomicity, health or causality."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .errors import AgentTaskError
from .receipts import effective_actions
from .service_observation import SERVICE_TOOLS, ServiceObservation, ServiceReceipt
from .service_operations import ServiceOperation

_DESIRED = {ServiceOperation.START: "running", ServiceOperation.STOP: "stopped"}


def validate_service_clause(clause: Mapping[str, Any]) -> None:
    """Require the fixed tool/state pair with no service name or authority overrides."""
    if set(clause) != {"kind", "tool", "state"} or clause["kind"] != "service_state":
        raise AgentTaskError("service completion requires exactly kind, tool and state")
    tool = clause["tool"]
    if type(tool) is not str or tool not in SERVICE_TOOLS or clause["state"] != _DESIRED[SERVICE_TOOLS[tool]]:
        raise AgentTaskError("service completion requires the tool's fixed desired state")


def service_matches(clause: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]],
                    observation: Mapping[str, Any]) -> bool | None:
    """Require the latest confirmed attempt and a new report from its retained owner."""
    validate_service_clause(clause)
    row = next((item for item in reversed(effective_actions(receipts))
                if item.get("command") == clause["tool"]), None)
    if row is None or row.get("status") != "confirmed":
        return None
    grounding = row.get("grounding")
    if not isinstance(grounding, Mapping) or not isinstance(grounding.get("service"), Mapping):
        return None
    before = ServiceObservation.from_dict(grounding["service"])
    accepted = ServiceReceipt.from_dict(row.get("result", {}))
    current = ServiceObservation.from_dict(observation)
    if not _same_attempt(row, before, accepted, current, clause["tool"]):
        return None
    return current.status.state.name.lower() == clause["state"]


def _same_attempt(row: Mapping[str, Any], before: ServiceObservation, accepted: ServiceReceipt,
                  current: ServiceObservation, tool: str) -> bool:
    return (row.get("id") == accepted.operation_id and accepted.operation is SERVICE_TOOLS[tool]
            and before.binding == accepted.binding == current.binding
            and before.finished <= accepted.accepted_at <= current.started
            and before.observation_id != current.observation_id)
