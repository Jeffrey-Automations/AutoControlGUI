"""Reviewed screen authority stays separate from tool behavior hints."""
from dataclasses import replace
import json

import pytest

from je_auto_control.utils.exception.exceptions import AutoControlActionException
from je_auto_control.utils.mcp_server.server import MCPServer
from je_auto_control.utils.mcp_server.tools import build_default_tool_registry, make_plugin_tool
from je_auto_control.utils.mcp_server.tools._base import MCPTool, READ_ONLY, schema
from je_auto_control.utils.rbac import AuthorizationContext, Role, authorization_scope
from je_auto_control.utils.rbac.policy import capability_for_tool
from je_auto_control.utils.rbac.tool_classification import SCREEN_SOURCE_TOOLS, SCREEN_TOOLS, TOOL_ALIASES
from je_auto_control.utils.rbac.users import Capability


def rpc(server, method, params=None, role=Role.VIEWER):
    with authorization_scope(AuthorizationContext(role, role)):
        return json.loads(server.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {},
        })))


@pytest.fixture(scope="module")
def registry():
    return {tool.name: tool for tool in build_default_tool_registry(read_only=False)}


def marker(tool):
    calls = []
    def invoke(**arguments):
        calls.append(arguments)
        return "allowed"
    return MCPServer(tools=[replace(tool, handler=invoke)]), calls


@pytest.mark.parametrize("name", [
    "ac_image_hash", "ac_dedupe_images", "ac_diff_screenshots", "diff_screens",
    "ac_locate_image_center", "find_image", "ac_wait_for_image", "wait_image",
    "ac_assert_image", "ac_assert_video_changes", "ac_wait_for_file",
    "ac_android_list_devices",
    "ac_android_device_info", "ac_android_screen_info", "ac_android_app_state",
    "ac_android_wait_for_app", "ac_ios_device_info", "ac_ios_screen_info",
    "ac_ios_app_state", "ac_ios_wait_for_app", "ac_ios_find_element", "ac_ios_dump_source",
])
def test_data_tools_are_hidden_and_refused_before_validation_or_handler(registry, name):
    server, calls = marker(registry[name])
    assert rpc(server, "tools/list")["result"]["tools"] == []
    reply = rpc(server, "tools/call", {"name": name, "arguments": {}})
    assert reply["error"]["data"]["required_capability"] == Capability.READ_DATA
    assert calls == []


@pytest.mark.parametrize("name", sorted(SCREEN_SOURCE_TOOLS))
def test_optional_source_preserves_live_screen_but_not_host_file_reads(registry, name):
    server, calls = marker(registry[name])
    assert rpc(server, "tools/list")["result"]["tools"][0]["name"] == name
    assert "result" in rpc(server, "tools/call", {"name": name, "arguments": {}})
    assert calls == [{}]
    reply = rpc(server, "tools/call", {"name": name, "arguments": {"source": "private.png"}})
    assert reply["error"]["data"]["required_capability"] == Capability.READ_DATA
    assert calls == [{}]
    assert "result" in rpc(server, "tools/call", {
        "name": name, "arguments": {"source": "private.png"}}, role=Role.OPERATOR)
    assert calls[-1] == {"source": "private.png"}


def test_alias_policy_has_one_canonical_source(registry):
    for short, canonical in TOOL_ALIASES.items():
        assert capability_for_tool(short, registry[short].annotations.read_only) == capability_for_tool(
            canonical, registry[canonical].annotations.read_only)
    assert SCREEN_TOOLS <= registry.keys()


def test_unreviewed_read_hint_does_not_grant_viewer_authority():
    tool = MCPTool("future_read", "future", schema({}), lambda: "private", READ_ONLY)
    server, calls = marker(tool)
    assert rpc(server, "tools/list")["result"]["tools"] == []
    assert "error" in rpc(server, "tools/call", {"name": tool.name, "arguments": {}})
    assert not calls
    assert "result" in rpc(server, "tools/call", {"name": tool.name, "arguments": {}}, role=Role.OPERATOR)


def test_plugin_read_hint_and_builtin_looking_name_are_not_grants():
    def read_data():
        return "private"
    read_data.mcp_read_only = True
    tool = make_plugin_tool("ac_screen_size", read_data)
    server, calls = marker(tool)
    assert tool.name.startswith("plugin_")
    assert rpc(server, "tools/list")["result"]["tools"] == []
    assert "error" in rpc(server, "tools/call", {"name": tool.name, "arguments": {}})
    assert not calls


def test_readonly_catalogue_excludes_caller_selected_executables(registry):
    readonly = {tool.name: tool for tool in build_default_tool_registry(read_only=True)}
    unsafe = {name for name, tool in registry.items() if "adb_path" in tool.input_schema.get("properties", {})}
    assert {"ac_android_list_devices", "ac_android_device_info", "ac_android_screen_info",
            "ac_android_app_state", "ac_android_wait_for_app"} <= unsafe
    assert not unsafe.intersection(readonly)
    server = MCPServer(tools=readonly.values())
    reply = rpc(server, "tools/call", {"name": "ac_android_list_devices",
                "arguments": {"adb_path": "must-never-run.exe"}}, role=Role.OPERATOR)
    assert "error" in reply
    full, calls = marker(registry["ac_android_list_devices"])
    assert "result" in rpc(full, "tools/call", {"name": "ac_android_list_devices",
                          "arguments": {"adb_path": "must-never-run.exe"}}, role=Role.OPERATOR)
    assert calls == [{"adb_path": "must-never-run.exe"}]


@pytest.mark.parametrize("name", ["ac_assert_text", "ac_assert_image", "ac_assert_pixel", "ac_assert_window"])
def test_readonly_capture_guard_applies_even_without_schema_validation(name):
    readonly = {tool.name: tool for tool in build_default_tool_registry(read_only=True)}
    calls = []
    tool = replace(readonly[name], handler=lambda **args: calls.append(args))
    assert tool.input_schema["properties"]["capture_on_fail"]["enum"] == [False]
    with pytest.raises(AutoControlActionException, match="read-only"):
        tool.invoke({"capture_on_fail": True})
    assert calls == []
    tool.invoke({"capture_on_fail": False})
    assert calls == [{"capture_on_fail": False}]


def test_viewer_cannot_request_capture_artifact_in_full_registry(registry):
    server, calls = marker(registry["ac_assert_text"])
    reply = rpc(server, "tools/call", {"name": "ac_assert_text", "arguments": {
        "text": "known", "capture_on_fail": True}})
    assert reply["error"]["data"]["required_capability"] == Capability.DRIVE_INPUT
    assert calls == []


@pytest.mark.parametrize("name", sorted(SCREEN_TOOLS))
def test_reviewed_screen_names_reach_marker_for_viewer(registry, name):
    # Schema-independent dispatch probe; the real handler is never executed.
    server, calls = marker(replace(registry[name], input_schema=schema({})))
    assert rpc(server, "tools/list")["result"]["tools"][0]["name"] == name
    assert "result" in rpc(server, "tools/call", {"name": name, "arguments": {}})
    assert calls == [{}]


@pytest.mark.parametrize("name", ["ac_anchor_locate", "ac_anchor_locate_all"])
@pytest.mark.parametrize("field", ["anchor", "target"])
@pytest.mark.parametrize("kind, capability", [("image", Capability.READ_DATA), ("vlm", Capability.DRIVE_INPUT)])
def test_anchor_authority_checks_each_locator_before_handler(registry, name, field, kind, capability):
    server, calls = marker(registry[name])
    args = {"anchor": {"kind": "a11y", "name": "label"}, "target": {"kind": "ocr", "text": "value"}}
    assert "result" in rpc(server, "tools/call", {"name": name, "arguments": args})
    assert calls == [args]
    changed = {**args, field: {"kind": kind}}
    denied = rpc(server, "tools/call", {"name": name, "arguments": changed})
    assert denied["error"]["data"]["required_capability"] == capability
    assert calls == [args]


@pytest.mark.parametrize("name", ["ac_anchor_locate", "ac_anchor_locate_all"])
def test_readonly_anchors_reject_vlm_even_without_schema_validation(name):
    readonly = {tool.name: tool for tool in build_default_tool_registry(read_only=True)}
    calls = []
    tool = replace(readonly[name], handler=lambda **args: calls.append(args))
    safe = {"anchor": {"kind": "a11y"}, "target": {"kind": "ocr"}}
    tool.invoke(safe)
    for field in ("anchor", "target"):
        with pytest.raises(AutoControlActionException, match="read-only"):
            tool.invoke({**safe, field: {"kind": "vlm"}})
    assert calls == [safe]


def test_configuration_env_lookup_requires_data_authority(registry, monkeypatch):
    monkeypatch.setenv("AUTOCONTROL_RBAC_TEST_SECRET", "must-not-leak")
    server = MCPServer(tools=[registry["ac_validate_config"]])
    args = {"schema": {"key": {"env": "AUTOCONTROL_RBAC_TEST_SECRET"}}, "config": {}}
    denied = rpc(server, "tools/call", {"name": "ac_validate_config", "arguments": args})
    assert denied["error"]["data"]["required_capability"] == Capability.READ_DATA
    assert "must-not-leak" not in str(denied)
    args["config"] = {"key": "caller-value"}
    allowed = rpc(server, "tools/call", {"name": "ac_validate_config", "arguments": args})
    assert "result" in allowed
    assert "caller-value" in str(allowed)
    assert "must-not-leak" not in str(allowed)


@pytest.mark.parametrize("schema_value", [{"key": {"env": "SECRET"}}, '{"key": {"env": "SECRET"}}'])
def test_config_guard_handles_both_adapter_input_forms(schema_value):
    from je_auto_control.utils.rbac.tool_classification import argument_capability
    assert argument_capability("ac_validate_config", {"schema": schema_value, "config": {}}) == Capability.READ_DATA
    assert argument_capability("ac_validate_config", {
        "schema": schema_value, "config": '{"key": "caller"}'}) is None


@pytest.mark.parametrize("target", ["https://example.invalid/path", "mailto:user@example.invalid"])
def test_url_open_plan_remains_viewer_visible(registry, target):
    server, calls = marker(registry["ac_plan_open"])
    assert "result" in rpc(server, "tools/call", {"name": "ac_plan_open", "arguments": {"target": target}})
    assert calls == [{"target": target}]


@pytest.mark.parametrize("target", ["~/private", "relative/file", "C:\\private"])
def test_file_open_plan_requires_host_data_authority(registry, target):
    server, calls = marker(registry["ac_plan_open"])
    denied = rpc(server, "tools/call", {"name": "ac_plan_open", "arguments": {"target": target}})
    assert denied["error"]["data"]["required_capability"] == Capability.READ_DATA
    assert calls == []


def test_annotation_formatting_preserves_stdio_protocol(monkeypatch):
    import io
    readonly = {tool.name: tool for tool in build_default_tool_registry(read_only=True)}
    server = MCPServer(tools=[readonly["ac_ci_annotations"]])
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "ac_ci_annotations", "arguments": {"annotations": [{"message": "line\nnext"}]}}}
    output = io.StringIO()
    monkeypatch.setattr("sys.stdout", output)
    with authorization_scope(AuthorizationContext("viewer", Role.VIEWER)):
        server.serve_stdio(stdin=io.StringIO(json.dumps(request) + "\n"))
    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    reply = json.loads(lines[0])
    assert reply["id"] == 1
    content = json.loads(reply["result"]["content"][0]["text"])
    assert content == {"lines": ["::error::line%0Anext"]}


@pytest.mark.parametrize("name", ["ac_web_current_url", "ac_web_list_commands", "ac_list_plugins"])
def test_external_initialization_unknowns_do_not_gain_viewer_authority(registry, name):
    server, calls = marker(registry[name])
    denied = rpc(server, "tools/call", {"name": name, "arguments": {}})
    assert denied["error"]["data"]["required_capability"] == Capability.READ_DATA
    assert calls == []


def test_unknown_external_initialization_is_excluded_from_readonly():
    readonly = {tool.name for tool in build_default_tool_registry(read_only=True)}
    assert not {"ac_list_plugins", "ac_web_list_commands", "ac_web_current_url"}.intersection(readonly)


@pytest.mark.parametrize("name", ["ac_android_list_devices", "ac_android_device_info", "ac_android_screen_info",
                                  "ac_android_app_state", "ac_android_wait_for_app"])
def test_android_executable_override_requires_drive_authority(name):
    from je_auto_control.utils.rbac.tool_classification import argument_capability
    assert argument_capability(name, {}) is None
    assert argument_capability(name, {"adb_path": "sentinel-never-executed"}) == Capability.DRIVE_INPUT


def test_readonly_capture_schema_guard_also_applies_to_custom_names():
    from je_auto_control.utils.mcp_server.tools._readonly import readonly_tools
    calls = []
    tool = MCPTool("custom_assert", "custom", schema({"capture_on_fail": {"type": "boolean"}}),
                   lambda **args: calls.append(args), READ_ONLY)
    readonly = readonly_tools([tool])[0]
    with pytest.raises(AutoControlActionException, match="read-only"):
        readonly.invoke({"capture_on_fail": "truthy"})
    assert calls == []
    readonly.invoke({"capture_on_fail": False})
    assert calls == [{"capture_on_fail": False}]
