"""WDA remote adapter: no provider means no readiness, and every call needs a trusted device writer. No Qt."""
from __future__ import annotations

import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from je_auto_control.utils.agent_runtime.context import TaskOperation, operation_scope
from je_auto_control.utils.agent_runtime.errors import AgentObservationStale, AgentTaskError
from je_auto_control.utils.agent_runtime.ios_adapter import (
    IosCommandLease, IosDeviceSession, IosRemoteAdapter, check_ios_arguments,
)
from je_auto_control.utils.agent_runtime.models import AgentTaskSpec

BUNDLE = "org.example.app"
DEVICE = "00008110-000A1B2C3D4E5F60"


class Wda:
    def __init__(self):
        self.current = {"bundleId": BUNDLE, "pid": 321, "name": "App"}
        self.state, self.size, self.orientation, self.calls = 4, SimpleNamespace(width=390, height=844), "PORTRAIT", 0
        self.hang = False

    def app_current(self):
        self.calls += 1
        if self.hang:
            time.sleep(2)
        return self.current

    def app_state(self, bundle):
        assert bundle == BUNDLE
        return {"value": self.state}

    def window_size(self):
        return self.size


class Control:
    def __init__(self):
        self.ready_value, self.takeover, self.leases, self.fenced = (True, ""), None, [], []
        self.revoked = False

    def ready(self, snapshot, spec):
        return self.ready_value

    def checkpoint(self, physical_id):
        assert physical_id == DEVICE
        if self.revoked:
            raise AgentTaskError("provider revoked")

    def set_takeover_handler(self, handler):
        self.takeover = handler

    def lease(self, proposal, request_id):
        @contextmanager
        def fence():
            self.fenced.append("in")
            yield
            self.fenced.append("out")

        def dispatch(name, arguments, deadline, check):
            check()
            self.leases.append((name, arguments))
            return {"ios_phase": "returned", "may_have_effect": True}

        def settle():
            return {"device": {"platform": "ios", "physical_id": DEVICE}, "epoch": "e1", "inputs_released": True,
                    "queue_empty": True, "request_id": request_id}
        return IosCommandLease(proposal, request_id, "e1", fence, lambda: self.checkpoint(DEVICE), dispatch, settle)


def spec(tools=("AC_ios_tap",), apps=(BUNDLE,)):
    return AgentTaskSpec.from_dict({"goal": "fixture iOS tap", "target": "fixture", "apps": list(apps),
                                    "allowed_tools": list(tools), "budget": {"action_seconds": 1},
                                    "success_criteria": [{"kind": "actions_complete"}]})


@pytest.fixture
def adapter():
    wda, control = Wda(), Control()
    task = spec()
    session = IosDeviceSession(wda, physical_id=DEVICE, bundle_id=BUNDLE)
    with operation_scope(TaskOperation(task, lambda: None, None)):
        yield IosRemoteAdapter(session, control=control), wda, control, task


def test_without_a_provider_readiness_is_withheld_before_any_wda_call():
    wda, task = Wda(), spec()
    adapter = IosRemoteAdapter(IosDeviceSession(wda, physical_id=DEVICE, bundle_id=BUNDLE))
    with operation_scope(TaskOperation(task, lambda: None, None)):
        assert adapter.ready(task) == (False, "iOS trusted device fencing/presence/settlement provider is not configured")
        with pytest.raises(AgentTaskError, match="trusted device-control provider"):
            adapter.checkpoint()
    assert wda.calls == 0


@pytest.mark.parametrize("tools, apps", [(("AC_ios_type",), (BUNDLE,)), (("AC_ios_tap",), ("org.other.app",))])
def test_an_unreviewed_tool_or_bundle_is_not_ready(tools, apps):
    wda, task = Wda(), spec(tools, apps)
    adapter = IosRemoteAdapter(IosDeviceSession(wda, physical_id=DEVICE, bundle_id=BUNDLE), control=Control())
    with operation_scope(TaskOperation(task, lambda: None, None)):
        assert adapter.ready(task)[0] is False
    assert wda.calls == 0


def test_observe_and_prepare_bind_one_call_to_a_fresh_device_lease(adapter):
    adapter, _wda, control, task = adapter
    assert adapter.ready(task) == (True, "")
    observed = adapter.observe()
    assert observed["identity"] == {"platform": "ios", "physical_id": DEVICE, "bundle_id": BUNDLE, "app_state": 4,
                                    "display_size": [390, 844], "orientation": "PORTRAIT"}
    assert observed["elements"] == [] and observed["text"] == ""
    action = adapter.prepare("AC_ios_tap", {"x": 10, "y": 20})
    assert action.device == adapter.device == {"platform": "ios", "physical_id": DEVICE}
    assert action.invoke() == {"ios_phase": "returned", "may_have_effect": True}
    assert control.leases == [("AC_ios_tap", {"x": 10, "y": 20})] and control.fenced == ["in", "out"]
    assert action.settle() == {"device": {"platform": "ios", "physical_id": DEVICE}, "epoch": "e1",
                               "inputs_released": True, "queue_empty": True}
    with pytest.raises(AgentTaskError, match="replayed"):
        action.invoke()
    with pytest.raises(AgentObservationStale):
        adapter.prepare("AC_ios_tap", {"x": 10, "y": 20})  # the observation was consumed


@pytest.mark.parametrize("change", ["bundle", "state", "size", "orientation"])
def test_changed_metadata_since_observation_is_refused(adapter, change):
    adapter, wda, _control, task = adapter
    adapter.ready(task)
    adapter.observe()
    if change == "bundle":
        wda.current = {"bundleId": "org.other.app", "pid": 1}
    elif change == "state":
        wda.state = 3
    elif change == "size":
        wda.size = SimpleNamespace(width=844, height=390)
    else:
        wda.orientation = "LANDSCAPE"
    with pytest.raises(AgentObservationStale):
        adapter.prepare("AC_ios_tap", {"x": 1, "y": 1})


def test_a_background_bundle_is_not_ready(adapter):
    adapter, wda, _control, task = adapter
    wda.state = 3
    assert adapter.ready(task) == (False, "iOS host-bound bundle is not in the foreground")


def test_a_revoked_provider_stops_the_call_before_its_writer(adapter):
    adapter, _wda, control, task = adapter
    adapter.ready(task)
    adapter.observe()
    action = adapter.prepare("AC_ios_tap", {"x": 1, "y": 1})
    control.revoked = True
    with pytest.raises(AgentTaskError, match="revoked"):
        action.invoke()
    assert control.leases == []


def test_a_wda_read_past_its_deadline_is_unavailable(adapter):
    adapter, wda, _control, task = adapter
    wda.hang = True
    with pytest.raises(AgentTaskError, match="metadata is unavailable"):
        adapter.ready(task)


@pytest.mark.parametrize("name, arguments", [
    ("AC_ios_tap", {"x": -1, "y": 0}), ("AC_ios_tap", {"x": True, "y": 0}), ("AC_ios_tap", {"x": 1, "y": 1, "z": 1}),
    ("AC_ios_swipe", {"x1": 1, "y1": 1, "x2": 2, "y2": 2, "duration_s": 5}),
    ("AC_ios_press_key", {"key": "lock"}), ("AC_ios_press_key", {"key": []}), ("AC_ios_type", {"text": "hi"}),
])
def test_only_closed_argument_shapes_are_accepted(name, arguments):
    with pytest.raises(AgentTaskError):
        check_ios_arguments(name, arguments)


def test_valid_argument_shapes_pass():
    check_ios_arguments("AC_ios_swipe", {"x1": 1, "y1": 1, "x2": 2, "y2": 2, "duration_s": 0.5})
    check_ios_arguments("AC_ios_press_key", {"key": "home"})


@pytest.mark.parametrize("bundle", ["noDots", "a..b", "x" * 300])
def test_invalid_bundle_identifiers_are_refused(bundle):
    with pytest.raises(AgentTaskError):
        IosDeviceSession(Wda(), physical_id=DEVICE, bundle_id=bundle)
