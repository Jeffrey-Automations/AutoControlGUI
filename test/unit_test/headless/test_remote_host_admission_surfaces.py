"""``max_pending_handshakes`` and ``auth_timeout`` reach the host from every headless surface.

The registry's start helpers, the ``AC_start_remote_host`` / ``AC_start_ws_host``
commands and the ``ac_remote_host_start`` MCP tool each pass both settings to
the host they start, and refuse a bad value before stopping the running host.
Hosts bind loopback; no real input or capture runs.
"""
import math

import pytest

from je_auto_control.utils.executor.action_executor import Executor
from je_auto_control.utils.mcp_server.tools import build_default_tool_registry
from je_auto_control.utils.mcp_server.tools import _handlers_remote as handlers
from je_auto_control.utils.remote_desktop import host_admission
from je_auto_control.utils.remote_desktop.registry import registry

_FRAME = b"\xff\xd8fake"


@pytest.fixture(autouse=True)
def _no_screen(monkeypatch):
    """Hosts started here stream a fixed fake frame, never the real screen."""
    from je_auto_control.utils.remote_desktop import host as host_module
    monkeypatch.setattr(host_module, "_default_frame_provider", lambda *_a, **_k: lambda: _FRAME)
    monkeypatch.setattr(host_module, "_resolve_cursor_provider", lambda *_a, **_k: None)
    monkeypatch.setattr(host_module, "capture_origin", lambda _region: (0, 0))
    yield
    registry.stop_host()
    registry.stop_ws_host()


def _settings(host):
    return host._max_pending_handshakes, host._auth_timeout


@pytest.mark.parametrize("start, current", [
    (registry.start_host, lambda: registry.host),
    (registry.start_ws_host, lambda: registry._ws_host),
])
def test_the_registry_passes_both_settings_to_the_host(start, current):
    start("t", max_pending_handshakes=3, auth_timeout=2.5)
    assert _settings(current()) == (3, 2.5)


@pytest.mark.parametrize("start, current", [
    (registry.start_host, lambda: registry.host),
    (registry.start_ws_host, lambda: registry._ws_host),
])
def test_the_registry_defaults_are_the_hosts(start, current):
    start("t")
    assert _settings(current()) == (host_admission.DEFAULT_MAX_PENDING_HANDSHAKES,
                                    host_admission.DEFAULT_AUTH_TIMEOUT_S)


@pytest.mark.parametrize("kwargs", [
    {"max_pending_handshakes": 0}, {"max_pending_handshakes": 2.5}, {"max_pending_handshakes": True},
    {"max_pending_handshakes": "8"}, {"auth_timeout": 0}, {"auth_timeout": 61},
    {"auth_timeout": math.nan}, {"auth_timeout": True}, {"auth_timeout": "10"},
])
def test_a_bad_value_is_refused_before_the_running_host_is_stopped(kwargs):
    registry.start_host("t")
    running = registry.host
    with pytest.raises(ValueError):
        registry.start_host("t", **kwargs)
    assert registry.host is running and running.is_running


@pytest.mark.parametrize("command, current", [
    ("AC_start_remote_host", lambda: registry.host),
    ("AC_start_ws_host", lambda: registry._ws_host),
])
def test_the_start_commands_pass_both_settings(command, current):
    Executor().execute_action(
        [[command, {"token": "t", "max_pending_handshakes": 4, "auth_timeout": 5}]],
        raise_on_error=True,
    )
    assert _settings(current()) == (4, 5.0)


def test_the_mcp_tool_passes_both_settings():
    handlers.remote_host_start("t", max_pending_handshakes=2, auth_timeout=7.5)
    assert _settings(registry.host) == (2, 7.5)


def test_the_mcp_schema_declares_both_settings_with_their_bounds():
    tool = {tool.name: tool for tool in build_default_tool_registry()}["ac_remote_host_start"]
    properties = tool.input_schema["properties"]
    assert properties["max_pending_handshakes"]["type"] == "integer"
    assert properties["max_pending_handshakes"]["minimum"] == 1
    assert properties["auth_timeout"]["type"] == "number"
    assert properties["auth_timeout"]["exclusiveMinimum"] == 0
    assert properties["auth_timeout"]["maximum"] == 60
    assert "max_pending_handshakes" not in tool.input_schema["required"]
