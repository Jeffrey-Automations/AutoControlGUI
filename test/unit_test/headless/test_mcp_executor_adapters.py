"""Registry adapters preserve executor forwarding without driving native inputs."""

from unittest.mock import Mock

import pytest

from je_auto_control.utils.executor import action_executor
from je_auto_control.utils.mcp_server.tools import build_default_tool_registry


@pytest.mark.parametrize(
    "domain,tool_name,params,target,args,kwargs",
    [
        (
            "accessibility",
            "ac_a11y_record_start",
            {"poll_interval_s": "0.5", "min_movement_px": "12"},
            "_a11y_record_start",
            (),
            {"app_name": None, "poll_interval_s": 0.5, "min_movement_px": 12},
        ),
        ("data", "ac_normalize_text", {"text": "Example"}, "_normalize_text", ("Example", "NFKC", True, True), {}),
        (
            "desktop",
            "ac_drag_path",
            {"waypoints": [[1, 2], [3, 4]]},
            "_drag_path",
            ([[1, 2], [3, 4]], "mouse_left", "linear", 20, 0.0, 0.0),
            {},
        ),
        (
            "automation",
            "ac_run_agent",
            {"goal": "fake only", "max_steps": "2"},
            "_run_agent",
            (),
            {
                "goal": "fake only",
                "backend": "anthropic",
                "max_steps": 2,
                "wall_seconds": 300.0,
                "model": None,
                "max_tokens": 1024,
            },
        ),
        (
            "mobile",
            "ac_ios_swipe",
            {"x1": "1", "y1": "2", "x2": "3", "y2": "4"},
            "_ac_ios_swipe",
            (),
            {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "duration_s": 0.5, "url": None},
        ),
        (
            "vision",
            "ac_match_template",
            {"template": "fake.png"},
            "_match_template",
            ("fake.png", 0.8, None, None, "ccoeff_normed"),
            {},
        ),
    ],
)
def test_domain_adapter_forwarding(monkeypatch, domain, tool_name, params, target, args, kwargs):
    result = {"stub_result": [1, 2, 3]}
    stub = Mock(return_value=result)
    monkeypatch.setattr(action_executor, target, stub)
    tool = next(tool for tool in build_default_tool_registry() if tool.name == tool_name)
    assert tool.handler.__module__.endswith(f"._handlers_{domain}_executor")
    assert tool.handler(**params) is result
    stub.assert_called_once_with(*args, **kwargs)
