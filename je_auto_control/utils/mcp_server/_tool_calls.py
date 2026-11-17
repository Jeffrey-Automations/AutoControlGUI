"""The ``tools/call`` path of :class:`MCPServer`: admit, run, audit and answer one call.

Split out of ``server.py``, which had reached 745 of its 750 lines. Admission
(:meth:`ToolCallMixin._prepare_tool_call`) checks the request, RBAC, the
disclosed catalogue, the tool's schema, the argument policy, the rate limit
and the destructive-tool confirmation; :meth:`ToolCallMixin._handle_tools_call`
runs the tool with a fresh :class:`ToolCallContext`, records the outcome in
the audit log and turns the result, or any failure, into a ``tools/call``
result.

The failure screenshot is looked up on ``server`` at call time, so
``server._capture_error_screenshot`` stays the seam callers and tests replace.
"""
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.logging.secret_scope import secret_log_scope
from je_auto_control.utils.mcp_server._authz import authorize_tool_call, capture_error_artifact
from je_auto_control.utils.mcp_server._input_required import AnsweredByGate
from je_auto_control.utils.mcp_server._protocol import (
    _InvalidToolArguments, _MCPError, _to_content_blocks,
)
from je_auto_control.utils.mcp_server.context import OperationCancelledError, ToolCallContext
from je_auto_control.utils.mcp_server.tools._base import _tool_result_error
from je_auto_control.utils.mcp_server.tools._validation import (
    undeclared_arguments, validate_arguments,
)


def _error_screenshot(name: str) -> Optional[str]:
    """``server._capture_error_screenshot``, resolved when a tool fails."""
    from je_auto_control.utils.mcp_server import server
    return server._capture_error_screenshot(name)


class ToolCallMixin:
    """Admission and execution of ``tools/call`` for :class:`MCPServer`."""

    if TYPE_CHECKING:
        _tools: Dict[str, Any]
        _audit: Any
        _rate_limiter: Any
        _read_only_tools: bool
        _calls_lock: Any
        _active_calls: Dict[Any, ToolCallContext]
        _active_argument_policy: Any
        _agent_session: str
        _connection_id: Any
        _notifier: Optional[Callable[[str, Dict[str, Any]], None]]

        # Provided by DisclosureServerMixin / ClientRequestMixin; the stubs
        # mirror their parameters so the combined MCPServer type-checks.
        def _tool_for_invocation(self, tool: Any) -> Any: ...
        def _require_disclosed_tool(self, name: str, view: Any = None, tool: Any = None) -> None: ...
        def _maybe_confirm_destructive(self, name: str, tool: Any, arguments: Dict[str, Any]) -> None: ...
        def _accepted_tool_view(self) -> Any: ...
        def _call_tool_catalog(self, view: Any = None) -> Callable[[], Any]: ...

    def _prepare_tool_call(
        self, params: Dict[str, Any], tool_view: Any = None,
    ) -> tuple[str, Any, Dict[str, Any]]:
        """Validate a tools/call request; return ``(name, tool, arguments)``.

        Raises :class:`_MCPError` when the request is malformed, the tool is
        unknown or the rate limit is hit, and :class:`_InvalidToolArguments`
        when the arguments fail the tool's schema or name a path or value
        reference the configured :attr:`argument_policy` refuses. The
        arguments returned carry the canonical form of every checked path.
        """
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            raise _MCPError(-32602, "tools/call requires string 'name'")
        if not isinstance(arguments, dict):
            raise _MCPError(-32602, "tools/call 'arguments' must be an object")
        tool = self._tools.get(name)
        if tool is None:
            raise _MCPError(-32602, f"Unknown tool: {name}")
        tool = self._tool_for_invocation(tool)
        authorize_tool_call(tool, arguments, self._audit)  # RBAC; a no-op without a user
        self._require_disclosed_tool(name, tool_view, tool)
        violation = (validate_arguments(tool.input_schema, arguments)
                     or undeclared_arguments(tool.input_schema, arguments))
        if violation is not None:
            raise _InvalidToolArguments(f"Invalid arguments for {name}: {violation}")
        try:
            arguments = self._active_argument_policy.apply(name, tool.input_schema, arguments)
        except AutoControlException as error:
            raise _InvalidToolArguments(f"Invalid arguments for {name}: {error}") from error
        if self._rate_limiter is not None and not self._rate_limiter.try_acquire():
            raise _MCPError(-32000, f"Rate limit exceeded for tool {name!r}")
        self._maybe_confirm_destructive(name, tool, arguments)
        return name, tool, arguments

    @secret_log_scope()
    def _handle_tools_call(self, msg_id: Any,
                           params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            view = self._accepted_tool_view()
            name, tool, arguments = self._prepare_tool_call(params, view)
        except _InvalidToolArguments as error:
            return {"content": [{"type": "text", "text": str(error)}], "isError": True}
        except AnsweredByGate as answered:
            return answered.result
        ctx = self._build_call_context(msg_id, params, view)
        call_key = (self._connection_id, msg_id)
        with self._calls_lock:
            self._active_calls[call_key] = ctx
        started_at = time.monotonic()
        try:
            result = tool.invoke(arguments, ctx=ctx)
        except OperationCancelledError:
            self._audit.record(
                tool=name, arguments=arguments, status="cancelled",
                duration_seconds=time.monotonic() - started_at,
            )
            raise
        except _MCPError:
            raise
        # Any exception, not a list: re.PatternError, ET.ParseError, cv2.error or
        # a plugin's own error escaped the list, killed the worker thread and
        # left the call unanswered (stdio) or dropped the connection (HTTP).
        except Exception as error:  # noqa: BLE001  # reason: a tool's failure of any type must answer the call with isError
            return self._tool_failure(name, tool, arguments, error, started_at)
        finally:
            with self._calls_lock:
                self._active_calls.pop(call_key, None)
        failure = _tool_result_error(result)
        self._audit.record(
            tool=name, arguments=arguments, status="error" if failure is not None else "ok",
            duration_seconds=time.monotonic() - started_at,
            error_text=failure,
        )
        response: Dict[str, Any] = {
            "content": _to_content_blocks(result),
            "isError": failure is not None,
        }
        # 2025-06-18 spec: tools with an outputSchema return their dict result
        # as structuredContent for typed, token-cheap client consumption.
        if tool.output_schema is not None and isinstance(result, dict):
            response["structuredContent"] = result
        return response

    def _tool_failure(self, name: str, tool: Any, arguments: Dict[str, Any],
                      error: Exception, started_at: float) -> Dict[str, Any]:
        """Audit a tool that raised, with its failure screenshot, and answer ``isError``."""
        autocontrol_logger.warning("MCP tool %s failed: %r", name, error)
        artifact = capture_error_artifact(tool, self._read_only_tools, _error_screenshot)
        self._audit.record(
            tool=name, arguments=arguments, status="error",
            duration_seconds=time.monotonic() - started_at,
            error_text=f"{type(error).__name__}: {error}",
            artifact_path=artifact,
        )
        error_text = f"{type(error).__name__}: {error}"
        if artifact is not None:
            error_text += f"\n(error screenshot saved to {artifact})"
        return {
            "content": [{"type": "text", "text": error_text}],
            "isError": True,
        }

    def _build_call_context(self, msg_id: Any,
                            params: Dict[str, Any], tool_view: Any = None) -> ToolCallContext:
        meta = params.get("_meta") if isinstance(params.get("_meta"),
                                                  dict) else {}
        progress_token = meta.get("progressToken") if isinstance(meta, dict) else None
        return ToolCallContext(
            request_id=msg_id, progress_token=progress_token,
            notifier=self._notifier,
            path_policy=self._active_argument_policy.path_policy,
            session_id=f"{self._agent_session}:{self._connection_id}",
            tool_catalog=self._call_tool_catalog(tool_view),
        )


__all__ = ["ToolCallMixin"]
