"""An MCP tool call is a stoppable run that ``notifications/cancelled`` stops.

Before, the cancel only set the call's ``cancelled_event``: an action list
ran to its end and ``ac_wait_for_image`` / ``ac_wait_for_pixel`` slept on
``time.sleep`` until their timeout, out of reach of ``ac_stop_execution``.
"""
import json
import threading
import time
from typing import Any, Dict

import pytest

from je_auto_control.utils.executor.run_control import (
    active_executions, current_stop_token, stop_execution,
)
from je_auto_control.utils.mcp_server._call_run import MCP_RUN_PREFIX
from je_auto_control.utils.mcp_server.context import OperationCancelledError, ToolCallContext
from je_auto_control.utils.mcp_server.server import MCPServer
from je_auto_control.utils.mcp_server.tools import MCPTool, build_default_tool_registry

_EMPTY = {"type": "object", "properties": {}}


def _call(server: MCPServer, msg_id: int, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    raw = server.handle_line(json.dumps({
        "jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }))
    return json.loads(raw)


def _cancel(server: MCPServer, msg_id: int) -> None:
    server.handle_line(json.dumps({
        "jsonrpc": "2.0", "method": "notifications/cancelled",
        "params": {"requestId": msg_id, "reason": "test"},
    }))


def _start(server, msg_id, name, arguments):
    """Run one call on a thread; return (thread, holder) once it is a listed run."""
    holder: Dict[str, Any] = {}

    def run():
        holder["started"] = time.monotonic()
        holder["response"] = _call(server, msg_id, name, arguments)
        holder["finished"] = time.monotonic()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5.0
    while not any(r["run_id"].startswith(MCP_RUN_PREFIX) for r in active_executions()):
        assert time.monotonic() < deadline, "the call never became a stoppable run"
        time.sleep(0.01)
    return thread, holder


@pytest.fixture()
def never_matching_pixel(monkeypatch):
    import je_auto_control.wrapper.auto_control_screen as screen_module
    monkeypatch.setattr(screen_module, "get_pixel", lambda x, y, hwnd=None: (0, 0, 0))


def _wait_for_pixel_server() -> MCPServer:
    tools = [tool for tool in build_default_tool_registry() if tool.name == "ac_wait_for_pixel"]
    return MCPServer(tools=tools)


# One poll outlasts every bound below: only a wake mid-sleep can meet them.
_PIXEL_ARGS = {"x": 1, "y": 2, "target_rgb": [255, 0, 0], "timeout": 60.0, "poll": 30.0}


def test_cancel_wakes_wait_for_pixel_mid_poll(never_matching_pixel):
    server = _wait_for_pixel_server()
    thread, holder = _start(server, 11, "ac_wait_for_pixel", _PIXEL_ARGS)
    _cancel(server, 11)
    thread.join(timeout=10.0)
    assert not thread.is_alive()
    assert holder["response"]["error"]["code"] == -32800
    assert holder["finished"] - holder["started"] < 10.0
    assert active_executions() == []


def test_stop_execution_ends_wait_for_pixel_as_a_tool_error(never_matching_pixel):
    server = _wait_for_pixel_server()
    thread, holder = _start(server, 12, "ac_wait_for_pixel", _PIXEL_ARGS)
    assert stop_execution(reason="operator") == 1
    thread.join(timeout=10.0)
    assert not thread.is_alive()
    result = holder["response"]["result"]
    assert result["isError"] is True
    assert "ExecutionStopped" in result["content"][0]["text"]


def test_cancel_stops_an_action_list_the_call_runs():
    from je_auto_control.utils.executor.action_executor import execute_action
    reached = []

    def run_actions():
        execute_action([["AC_sleep", {"seconds": 30}]])
        reached.append("after")
        return "done"

    server = MCPServer(tools=[MCPTool(name="run_actions", description="d",
                                      input_schema=_EMPTY, handler=run_actions)])
    thread, holder = _start(server, 13, "run_actions", {})
    _cancel(server, 13)
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert holder["response"]["error"]["code"] == -32800
    assert reached == []


def test_list_executions_omits_its_own_call_but_lists_others(never_matching_pixel):
    tools = [tool for tool in build_default_tool_registry()
             if tool.name in {"ac_wait_for_pixel", "ac_list_executions"}]
    server = MCPServer(tools=tools)
    thread, _holder = _start(server, 14, "ac_wait_for_pixel", _PIXEL_ARGS)
    try:
        listing = _call(server, 15, "ac_list_executions", {})["result"]
        runs = listing.get("structuredContent", listing)
        text = json.dumps(runs)
        assert text.count(MCP_RUN_PREFIX) == 1
    finally:
        _cancel(server, 14)
        thread.join(timeout=5.0)


def test_a_cancel_that_arrives_before_the_run_still_stops_it():
    ctx = ToolCallContext(request_id=21)
    ctx.cancel()

    def handler():
        from je_auto_control.utils.executor.run_control import pause
        pause(30)
        return "slept"

    tool = MCPTool(name="sleepy", description="d", input_schema=_EMPTY, handler=handler)
    started = time.monotonic()
    with pytest.raises(OperationCancelledError):
        tool.invoke({}, ctx=ctx)
    assert time.monotonic() - started < 5.0
    assert ctx.stop_token is None


def test_invoke_without_a_server_context_is_not_a_run():
    seen = []
    tool = MCPTool(name="plain", description="d", input_schema=_EMPTY,
                   handler=lambda: seen.append(current_stop_token()) or "ok")
    assert tool.invoke({}) == "ok"
    assert seen == [None]


def test_failure_screenshot_is_still_looked_up_on_the_server_module(monkeypatch):
    # The tools/call path moved to _tool_calls.py; server._capture_error_screenshot
    # must remain the seam callers and tests replace.
    from je_auto_control.utils.mcp_server import server as server_module
    shots = []
    monkeypatch.setattr(server_module, "_capture_error_screenshot",
                        lambda name: shots.append(name) or "shot.png")

    def broken():
        raise RuntimeError("boom")

    server = MCPServer(tools=[MCPTool(name="broken", description="d",
                                      input_schema=_EMPTY, handler=broken)])
    result = _call(server, 31, "broken", {})["result"]
    assert result["isError"] is True
    assert "RuntimeError: boom" in result["content"][0]["text"]
    assert "(error screenshot saved to shot.png)" in result["content"][0]["text"]
    assert shots == ["broken"]
