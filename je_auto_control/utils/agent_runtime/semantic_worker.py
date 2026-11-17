"""Validate grounded helper requests against the worker's immutable task scope."""
from __future__ import annotations

from typing import Any, Mapping, NoReturn

from je_auto_control.utils.agent_runtime.context import current_operation
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.policy import TaskPolicy
from je_auto_control.utils.agent_runtime.semantic_target import SemanticTarget, _identifier, perform


def perform_grounded(target: Any, payload: Mapping[str, Any]) -> Any:
    """Reject unreviewed targets, malformed requests and out-of-scope tools before dispatch."""
    if not isinstance(target, SemanticTarget):
        raise AgentTaskError("grounded dispatch requires a semantic target")
    keys = {"tool", "arguments", "expected", "operation_id"}
    if not isinstance(payload, Mapping) or set(payload) != keys:
        raise AgentTaskError("invalid semantic command request")
    operation = current_operation()
    if operation is None:
        raise AgentTaskError("semantic dispatch requires a managed worker scope")
    operation.checkpoint()
    _identifier(payload["operation_id"])
    TaskPolicy(operation.spec).check(payload["tool"], payload["arguments"])
    result = perform(target, payload["tool"], payload["arguments"], observation=payload["expected"],
                     operation_id=payload["operation_id"])
    operation.checkpoint()
    return result


def require_empty_cleanup(payload: Mapping[str, Any]) -> None:
    """Semantic helpers have no desktop input to release, even during cleanup."""
    if payload != {"keys": [], "buttons": []}:
        raise AgentTaskError("semantic cleanup cannot release desktop input")


def refuse_cleanup_command(_name: str, _arguments: Any) -> NoReturn:
    """Resource retirement cannot create a new executable command scope."""
    raise AgentTaskError("semantic cleanup cannot dispatch commands")
