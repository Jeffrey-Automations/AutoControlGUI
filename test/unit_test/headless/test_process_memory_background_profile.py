"""The M0 routing profile: closed channels, no desktop-input route, no fallback, and the doc's matrix as data."""
import ast
from pathlib import Path
import re

import pytest

from je_auto_control.utils.process_memory import background_profile
from je_auto_control.utils.process_memory.background_profile import (
    DESKTOP_INPUT, WINDOWS_PROFILE, BackgroundProfile, BackgroundRoute, Channel, RouteState, route,
)
from je_auto_control.utils.process_memory.models import MemoryObservationError

_ROOT = Path(__file__).resolve().parents[3]
_CONTRACT = _ROOT / "docs" / "process_memory_contract.md"


def _matrix_labels() -> list:
    text = _CONTRACT.read_text(encoding="utf-8")
    section = text.split("## Windows capability matrix", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ") and not line.startswith("| Operation")]
    return [row.split("|")[1].strip() for row in rows if not set(row) <= set("|- ")]


def test_the_profile_is_the_contract_matrix_row_for_row():
    assert [item.label for item in WINDOWS_PROFILE.routes] == _matrix_labels()


def test_no_channel_is_desktop_input():
    assert not {channel.value for channel in Channel} & DESKTOP_INPUT


@pytest.mark.parametrize("state", [RouteState.EXISTING, RouteState.INJECTED_TESTS])
def test_a_route_that_can_serve_is_handed_back(state):
    profile = BackgroundProfile("windows", (
        BackgroundRoute("x.read", "X", Channel.OS_QUERY, True, "read only", state),))
    assert route(profile, "x.read").channel is Channel.OS_QUERY


def test_a_pending_or_unknown_operation_is_unsupported_not_a_fallback():
    for operation in ("application.command", "os.service", "ui.state", "click.button", "desktop_input"):
        with pytest.raises(MemoryObservationError, match="unsupported"):
            route(WINDOWS_PROFILE, operation)
    assert route(WINDOWS_PROFILE, "browser.state").channel is Channel.MANAGED_DOM


@pytest.mark.parametrize("channel", ["desktop_input", "mouse", "keyboard", "focus", "foreground", "uia_read"])
def test_a_route_can_only_name_a_closed_channel(channel):
    with pytest.raises(MemoryObservationError, match="unsupported"):
        BackgroundRoute("x.op", "X", channel, True, "requirement", RouteState.EXISTING)


@pytest.mark.parametrize("routes", [(), "duplicate"])
def test_a_profile_needs_unique_routes(routes):
    item = BackgroundRoute("x.op", "X", Channel.OS_QUERY, True, "requirement", RouteState.PENDING)
    with pytest.raises(MemoryObservationError, match="unsupported"):
        BackgroundProfile("windows", (item, item) if routes == "duplicate" else routes)


def test_writes_are_only_declared_by_command_channels():
    writing = {item.channel for item in WINDOWS_PROFILE.routes if not item.read_only}
    assert writing <= {Channel.APPLICATION_API, Channel.OS_SERVICE}
    assert all(item.read_only for item in WINDOWS_PROFILE.routes if item.channel is Channel.MEMORY_READ)


def test_the_profile_touches_no_desktop_input_or_native_code():
    tree = ast.parse(Path(background_profile.__file__).read_text(encoding="utf-8"))
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imported <= {"__future__", "dataclasses", "enum", "models"}, imported
    assert not re.search(r"ctypes|wrapper|keyboard|mouse|windows_native", " ".join(imported))
