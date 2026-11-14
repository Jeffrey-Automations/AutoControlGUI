"""Audited host-data reads deny viewer callers before handlers on every callable surface."""
from dataclasses import replace
import json

import pytest

import je_auto_control as ac
from je_auto_control.utils.mcp_server.audit import AuditLogger
from je_auto_control.utils.mcp_server.server import MCPServer
from je_auto_control.utils.mcp_server.tools import build_default_tool_registry
from je_auto_control.utils.rbac import AuthorizationContext, AuthorizationError, Capability, Role, authorization_scope
from je_auto_control.utils.rbac.policy import capability_for_command, capability_for_tool


_READS = (
    ("AC_probe_capabilities", "ac_probe_capabilities"),
    ("AC_diagnose", "ac_diagnose"),
    ("AC_remote_host_status", "ac_remote_host_status"),
    ("AC_remote_viewer_status", "ac_remote_viewer_status"),
    ("AC_usb_passthrough_status", "ac_usb_passthrough_status"),
    ("AC_usb_loopback_list", "ac_usb_loopback_list"),
    ("AC_usb_remote_list", "ac_usb_remote_list"),
)


@pytest.mark.parametrize("command,name", _READS)
def test_host_data_requires_data_authority_before_executor_or_mcp_handler(command, name, monkeypatch, tmp_path):
    calls = []
    def read():
        calls.append(name)
        return {"controlled": True}
    monkeypatch.setitem(ac.executor.event_dict, command, read)
    original = next(tool for tool in build_default_tool_registry(read_only=True) if tool.name == name)
    tool = replace(original, handler=read)
    server = MCPServer(tools=[tool], audit_logger=AuditLogger(str(tmp_path / "audit.jsonl")))
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": name, "arguments": {}}}
    with authorization_scope(AuthorizationContext("viewer", Role.VIEWER)):
        with pytest.raises(AuthorizationError) as denied:
            ac.execute_action([[command]], raise_on_error=True)
        assert denied.value.capability == Capability.READ_DATA
        with pytest.raises(AuthorizationError) as denied:
            tool.invoke({})
        assert denied.value.capability == Capability.READ_DATA
        reply = json.loads(server.handle_line(json.dumps(request)))
        assert reply["error"]["code"] == -32003
    assert calls == []
    assert capability_for_command(command) == capability_for_tool(name, True) == Capability.READ_DATA
    with authorization_scope(AuthorizationContext("operator", Role.OPERATOR)):
        ac.execute_action([[command]], raise_on_error=True)
        assert tool.invoke({}) == {"controlled": True}
        reply = json.loads(server.handle_line(json.dumps(request)))
        assert not reply["result"]["isError"]
    assert calls == [name, name, name]


@pytest.mark.parametrize("command", ["AC_list_usb_devices", "AC_usb_recent_events",
                                     "AC_inspector_recent", "AC_inspector_summary"])
@pytest.mark.parametrize("strict", [False, True])
def test_device_and_telemetry_commands_refuse_viewer_before_provider(command, strict, monkeypatch):
    calls = []
    monkeypatch.setitem(ac.executor.event_dict, command, lambda: calls.append(command))
    assert capability_for_command(command) == Capability.READ_DATA
    with authorization_scope(AuthorizationContext("viewer", Role.VIEWER)):
        if strict:
            with pytest.raises(AuthorizationError) as denied:
                ac.execute_action([[command]], raise_on_error=True)
            assert denied.value.capability == Capability.READ_DATA
        else:
            result = ac.execute_action([[command]])
            assert any("read_data" in str(value) for value in result.values())
    assert calls == []
    for role in (Role.OPERATOR, Role.ADMIN):
        with authorization_scope(AuthorizationContext(role, role)):
            ac.execute_action([[command]], raise_on_error=True)
    assert calls == [command, command]
