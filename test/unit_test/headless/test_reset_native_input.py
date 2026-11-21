"""Explicit reset of the cached Wayland input session, on every delivery surface. No Qt, no portal."""
import pytest

from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.wrapper.capabilities import BackendContext, reset_native_input


def context(platform, environ):
    return BackendContext(platform=platform, environ=environ)


def test_on_wayland_the_cached_session_and_refusal_are_retired():
    calls = []
    result = reset_native_input(context("linux", {"WAYLAND_DISPLAY": "wayland-0"}), reset=lambda: calls.append(True))
    assert calls == [True] and result["reset"] is True
    assert result["capabilities"]["display_server"] == "wayland"


@pytest.mark.parametrize("platform, environ", [("win32", {}), ("darwin", {}), ("linux", {"DISPLAY": ":0"})])
def test_elsewhere_nothing_is_reset(platform, environ):
    result = reset_native_input(context(platform, environ), reset=lambda: pytest.fail("reset called"))
    assert result["reset"] is False and result["capabilities"]["passive"] is True


def test_a_context_is_required():
    with pytest.raises(AutoControlException):
        reset_native_input("linux")


def test_the_reset_is_reachable_from_the_facade_executor_mcp_and_rbac():
    import je_auto_control
    from je_auto_control.utils.executor.action_executor import executor
    from je_auto_control.utils.mcp_server.tools import build_default_tool_registry
    from je_auto_control.utils.rbac.policy import COMMAND_CAPABILITIES, Capability
    assert je_auto_control.reset_native_input is reset_native_input
    assert "AC_reset_native_input" in executor.known_commands()
    tools = {tool.name: tool for tool in build_default_tool_registry(read_only=False, aliases=False)}
    assert "ac_reset_native_input" in tools and not tools["ac_reset_native_input"].annotations.read_only
    assert "ac_reset_native_input" not in {tool.name for tool in build_default_tool_registry(read_only=True)}
    assert COMMAND_CAPABILITIES["AC_reset_native_input"] == Capability.DRIVE_INPUT
