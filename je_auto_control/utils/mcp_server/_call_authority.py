"""Bind anonymous MCP sessions to operator authority across direct and nested tool calls."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from je_auto_control.utils.rbac.authorization import AuthorizationContext, AuthorizationError, current_authorization
from je_auto_control.utils.rbac.deferred import DeferredAuthorization
from je_auto_control.utils.rbac.policy import capabilities_for_tool_call, denied_command_in


@contextmanager
def invocation_authority(tool: Any, arguments: dict, context: Any) -> Iterator[None]:
    """Refresh an authenticated owner or derive a restricted session principal before any wrapper runs."""
    caller = current_authorization()
    session = getattr(context, "session_id", "")
    if caller is None and session:
        caller = AuthorizationContext("mcp:" + session, "operator")
    with DeferredAuthorization(caller).context_scope() as identity:
        if identity is not None:
            _require(identity, tool, arguments)
        yield


def _require(identity: AuthorizationContext, tool: Any, arguments: dict) -> None:
    for needed in capabilities_for_tool_call(tool.name, tool.annotations.read_only, arguments):
        if not identity.allows(needed):
            raise AuthorizationError(f"{tool.name} requires {needed}", capability=needed)
    denied = denied_command_in(arguments, identity)
    if denied is not None:
        raise AuthorizationError(f"{denied[0]} requires {denied[1]}", capability=denied[1])
