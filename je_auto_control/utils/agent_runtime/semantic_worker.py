"""Validate grounded helper requests against the worker's immutable task scope."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator, Mapping, NoReturn

from je_auto_control.utils.agent_runtime.context import (
    TaskOperation, authorization_key, current_operation, operation_scope,
)
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.models import AgentTaskSpec
from je_auto_control.utils.agent_runtime.policy import TaskPolicy
from je_auto_control.utils.agent_runtime.semantic_target import SemanticTarget, _identifier, perform
from je_auto_control.utils.rbac.authorization import AuthorizationContext, current_authorization
from je_auto_control.utils.rbac.deferred import DeferredAuthorization
from je_auto_control.utils.exception.exceptions import AutoControlException


def _refresh_authority(owner: AuthorizationContext | None) -> None:
    try:
        with DeferredAuthorization(owner).scope():
            unchanged = authorization_key(current_authorization()) == authorization_key(owner)
    except (AutoControlException, OSError, ValueError, TypeError, LookupError):
        raise AgentTaskError("semantic worker authority is unavailable") from None
    if not unchanged:
        raise AgentTaskError("semantic worker authority changed")


@contextmanager
def managed_semantic_scope(spec: AgentTaskSpec, owner: AuthorizationContext | None,
                           check: Callable[[], None]) -> Iterator[TaskOperation]:
    """Refresh the pinned owner before access and publication, including nested reads."""
    def validate() -> None:
        if (current_operation() is not request
                or authorization_key(current_authorization()) != authorization_key(owner)):
            raise AgentTaskError("semantic worker operation scope changed")
        _refresh_authority(owner)

    def checkpoint() -> None:
        validate()
        check()
        validate()

    request = TaskOperation(spec, checkpoint, owner)
    with operation_scope(request):
        checkpoint()
        yield request
        checkpoint()


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


def refuse_input(_event: dict[str, Any]) -> NoReturn:
    """Semantic request and retirement scopes never acknowledge desktop input."""
    raise AgentTaskError("semantic helpers cannot emit desktop input")
