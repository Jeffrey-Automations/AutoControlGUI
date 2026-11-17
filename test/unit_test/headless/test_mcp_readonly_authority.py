"""Host readonly ceilings and refreshed authority protect late invocation effects."""
from dataclasses import replace
import json

import pytest

from je_auto_control.utils.mcp_server.server import MCPServer
from je_auto_control.utils.mcp_server.tools import build_default_tool_registry
from je_auto_control.utils.rbac import AuthorizationContext, Role, authorization_scope
from je_auto_control.utils.rbac.authorization import AuthorizationError, resolve_token
from je_auto_control.utils.rbac.users import UserStore


def call(server, name, arguments, role=Role.OPERATOR):
    identity = AuthorizationContext(role, role) if role is not None else None
    with authorization_scope(identity):
        return json.loads(server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": arguments}})))


@pytest.fixture(scope="module")
def registry():
    return {tool.name: tool for tool in build_default_tool_registry(read_only=False)}


@pytest.mark.parametrize("dynamic", [False, True])
@pytest.mark.parametrize("name", ["ac_android_list_devices", "ac_web_current_url", "ac_list_plugins"])
def test_host_readonly_excludes_unsafe_descriptors_and_late_registration(registry, dynamic, name):
    calls = []
    tool = replace(registry[name], handler=lambda **args: calls.append(args))
    server = MCPServer(tools=[] if dynamic else [tool])
    server.configure_tool_disclosure("full", read_only=True)
    if dynamic:
        server.register_tool(tool)
    assert name not in server.tool_index().names()
    assert "error" in call(server, name, {})
    assert calls == []


@pytest.mark.parametrize("name, safe, unsafe", [
    ("ac_assert_text", {"text": "x"}, {"text": "x", "capture_on_fail": True}),
    ("ac_anchor_locate", {"anchor": {"kind": "a11y"}, "target": {"kind": "ocr"}},
     {"anchor": {"kind": "a11y"}, "target": {"kind": "vlm"}}),
])
def test_explicit_full_registry_gets_readonly_argument_variants(registry, name, safe, unsafe):
    calls = []
    original = replace(registry[name], handler=lambda **args: calls.append(args))
    server = MCPServer(tools=[original])
    server.configure_tool_disclosure("full", read_only=True)
    assert call(server, name, safe)["result"]["isError"] is False
    assert call(server, name, unsafe)["result"]["isError"] is True
    assert calls == [safe]
    assert not original.enforce_readonly_arguments
    if name == "ac_assert_text":
        assert server.tool_index().get_schema(name)["inputSchema"]["properties"]["capture_on_fail"]["enum"] == [False]
        assert "enum" not in original.input_schema["properties"]["capture_on_fail"]


@pytest.mark.parametrize("readonly, variant, role, expected", [
    (False, False, Role.VIEWER, []), (False, False, Role.OPERATOR, ["ac_screen_size"]),
    (True, False, Role.OPERATOR, []), (True, False, None, []), (False, True, Role.OPERATOR, []),
])
def test_failure_artifacts_require_writable_tool_and_caller(registry, monkeypatch, readonly, variant, role, expected):
    captures = []
    monkeypatch.setenv("JE_AUTOCONTROL_MCP_ERROR_SHOTS", "must-not-be-used-directly")
    monkeypatch.setattr("je_auto_control.utils.mcp_server.server._capture_error_screenshot",
                        lambda name: captures.append(name))
    def fail():
        raise RuntimeError("fake handler failure")
    tool = replace(registry["ac_screen_size"], handler=fail, enforce_readonly_arguments=variant)
    server = MCPServer(tools=[tool])
    server.configure_tool_disclosure("full", read_only=readonly)
    assert call(server, tool.name, {}, role)["result"]["isError"] is True
    assert captures == expected


def test_readonly_vlm_rejection_never_captures_error_artifact(registry, monkeypatch):
    captures, calls = [], []
    monkeypatch.setattr("je_auto_control.utils.mcp_server.server._capture_error_screenshot",
                        lambda name: captures.append(name))
    tool = replace(registry["ac_anchor_locate"], handler=lambda **args: calls.append(args))
    server = MCPServer(tools=[tool])
    server.configure_tool_disclosure("full", read_only=True)
    args = {"anchor": {"kind": "vlm"}, "target": {"kind": "ocr"}}
    assert call(server, tool.name, args)["result"]["isError"] is True
    assert captures == calls == []


@pytest.mark.parametrize("name, args", [
    ("ac_image_histogram", {"source": "private.png"}),
    ("ac_assert_text", {"text": "x", "capture_on_fail": True}),
    ("ac_anchor_locate", {"anchor": {"kind": "vlm"}, "target": {"kind": "ocr"}}),
])
def test_direct_and_nested_invocations_require_argument_authority(registry, name, args):
    calls = []
    target = replace(registry[name], handler=lambda **values: calls.append(values))
    outer = replace(registry["ac_screen_size"], handler=lambda: target.invoke(args))
    with authorization_scope(AuthorizationContext("viewer", Role.VIEWER)):
        with pytest.raises(AuthorizationError):
            target.invoke(args)
        with pytest.raises(AuthorizationError):
            outer.invoke({})
    assert calls == []


@pytest.mark.parametrize("revoke", ["viewer", "missing", "invalid"])
def test_revocation_after_prepare_blocks_argument_dispatch_and_failure_capture(registry, monkeypatch, tmp_path, revoke):
    store = UserStore(tmp_path / "users.json")
    token = store.add_user(user_id="owner", display_name="owner", role=Role.OPERATOR)
    identity = resolve_token(store, token)
    calls, captures = [], []
    tool = replace(registry["ac_image_histogram"], handler=lambda **args: calls.append(args))
    server = MCPServer(tools=[tool])
    build = server._build_call_context
    def change_role(*args, **kwargs):
        context = build(*args, **kwargs)
        if revoke == "viewer":
            store.set_role("owner", Role.VIEWER)
        elif revoke == "missing":
            store.path.unlink()
        else:
            store.path.write_text("invalid", encoding="utf-8")
        return context
    monkeypatch.setattr(server, "_build_call_context", change_role)
    monkeypatch.setattr("je_auto_control.utils.mcp_server.server._capture_error_screenshot",
                        lambda name: captures.append(name))
    with authorization_scope(identity):
        response = json.loads(server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": tool.name, "arguments": {"source": "private.png"}}})))
    assert response["result"]["isError"] is True
    assert calls == captures == []


def test_host_readonly_preserves_safe_alias_after_dynamic_registration(registry):
    calls = []
    server = MCPServer(tools=[])
    server.configure_tool_disclosure("full", read_only=True)
    tool = replace(registry["mouse_pos"], handler=lambda **args: calls.append(args))
    server.register_tool(tool)
    assert "mouse_pos" in server.tool_index().names()
    assert call(server, "mouse_pos", {}, Role.VIEWER)["result"]["isError"] is False
    assert calls == [{}]
