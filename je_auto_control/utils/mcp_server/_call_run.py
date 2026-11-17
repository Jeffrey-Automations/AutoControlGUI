"""Run one MCP tool call as a stoppable executor run that its cancellation stops.

``notifications/cancelled`` used to set only the call's ``cancelled_event``:
a handler that polled :meth:`ToolCallContext.check_cancelled` noticed, but an
action list started by ``ac_execute_actions`` ran to its last action, and the
MCP polling waits (``ac_wait_for_image``, ``ac_wait_for_pixel``) slept through
the request. Every call that carries a :class:`ToolCallContext` now runs under
its own :class:`~je_auto_control.utils.executor.run_control.StopToken`:

* the client's cancel stops the token, so the executor halts at its next
  checkpoint and a wait sleeping on :func:`run_control.pause` wakes at once;
  the stop surfaces as :class:`OperationCancelledError`, which the server
  answers as a cancelled call rather than a tool failure;
* the call is listed by ``ac_list_executions`` and stopped by
  ``ac_stop_execution`` (or any other ``stop_execution()`` caller, such as the
  GUI) like every other stoppable run; such a stop is reported as the tool's
  error, because the client did not ask for it.

A call without a server context (``tool.invoke(arguments)`` from Python, or a
test's stand-in object) runs exactly as before.
"""
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from je_auto_control.utils.mcp_server.context import (
    CLIENT_CANCEL_REASON, OperationCancelledError, ToolCallContext,
)

#: Prefix of the run id an MCP tool call is listed under.
MCP_RUN_PREFIX = "mcp-"


@contextmanager
def tool_call_run(ctx: Any) -> Iterator[None]:
    """Run the block as the stoppable run of the MCP call ``ctx`` describes."""
    if not isinstance(ctx, ToolCallContext):
        yield
        return
    from je_auto_control.utils.executor.run_control import (
        ExecutionStopped, StopToken, stoppable_run,
    )
    token = StopToken(f"{MCP_RUN_PREFIX}{uuid.uuid4().hex[:12]}")
    ctx.stop_token = token
    if ctx.cancelled:   # cancelled before the token existed: ToolCallContext.cancel saw none
        token.stop(CLIENT_CANCEL_REASON)
    try:
        with stoppable_run(token=token):
            yield
    except ExecutionStopped as stopped:
        if ctx.cancelled:
            raise OperationCancelledError(ctx.request_id) from stopped
        raise
    finally:
        ctx.stop_token = None


__all__ = ["MCP_RUN_PREFIX", "tool_call_run"]
