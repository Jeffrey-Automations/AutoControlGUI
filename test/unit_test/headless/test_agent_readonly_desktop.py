"""Desktop read-only verification configures without a presence lease because the helper has no input path."""
import io
import sys
from unittest.mock import Mock

import pytest

from je_auto_control.utils.agent_runtime import AgentTaskError, AgentTaskSpec
from je_auto_control.utils.agent_runtime import native_worker
from je_auto_control.utils.agent_runtime.context import TaskOperation, operation_scope
from je_auto_control.utils.agent_runtime.input_journal import InputJournal
from je_auto_control.utils.agent_runtime.native_target import NativeDesktopTarget
from je_auto_control.utils.agent_runtime.native_worker import NativeWorker
from je_auto_control.utils.agent_runtime.readonly_target import CompletionReader, ReadOnlyNativeTarget
from je_auto_control.utils.agent_runtime.readonly_worker import ReadOnlyWorker

OBSERVATION = {"identity": "fake-desktop", "elements": [], "semantic_observation": False, "text_redacted": True}


def desktop_spec() -> AgentTaskSpec:
    return AgentTaskSpec.from_dict({
        "goal": "Reviewed completion: the document shows it was saved", "target": "local-desktop",
        "mode": "external", "apps": ["notepad.exe"], "allowed_tools": ["AC_click_mouse", "AC_focus_window"],
        "success_criteria": [{"kind": "element_present", "name": "Saved"}], "budget": {"action_seconds": 5}})


class FakeDesktop:
    """Stands in for the default DesktopTarget, so the worker still treats it as the standard target."""

    observe_hook = None

    def __init__(self):
        self.calls = []

    def ready(self, spec):
        self.calls.append(("ready", spec.target))
        return True, ""

    def observe(self):
        self.calls.append(("observe",))
        if self.observe_hook is not None:
            self.observe_hook()
        return dict(OBSERVATION)

    def perform(self, name, arguments):
        raise AssertionError(f"desktop target performed {name}")

    def prepare_input(self, event):
        raise AssertionError("desktop target prepared input")

    def validate_input(self, event):
        raise AssertionError("desktop target validated input")

    def cleanup(self):
        self.calls.append(("cleanup",))


@pytest.fixture
def standard_desktop(monkeypatch):
    monkeypatch.setattr(native_worker, "DesktopTarget", FakeDesktop)
    monkeypatch.setattr(FakeDesktop, "observe_hook", None)


def configure(worker, **extra):
    return worker._dispatch("configure", {"spec": desktop_spec().to_dict(), "owner": {}, **extra})


# (a) a desktop read-only verification now configures and completes.

def test_readonly_worker_configures_observes_and_retires_a_desktop_task_without_presence(standard_desktop):
    sink = io.BytesIO()
    worker = ReadOnlyWorker(io.BytesIO(), sink)
    assert not worker._custom_target
    assert configure(worker) == {"ready": True, "reason": ""}
    assert worker._dispatch("observe", {}) == OBSERVATION
    assert worker._dispatch("cleanup", {"keys": [], "buttons": []}) == {"cleaned": True}
    assert worker._target.calls == [("ready", "local-desktop"), ("observe",), ("cleanup",)]
    assert worker._presence_binding is None and worker._activity is None
    assert sink.getvalue() == b""
    worker.close()


HELPER = '''
import sys
from je_auto_control.utils.agent_runtime import native_worker
class Desktop:
    def ready(self, spec):
        return True, ""
    def observe(self):
        return {"identity": "fake-desktop", "elements": [], "semantic_observation": False, "text_redacted": True}
    def cleanup(self):
        pass
native_worker.DesktopTarget = Desktop
from je_auto_control.utils.agent_runtime.readonly_worker import ReadOnlyWorker
ReadOnlyWorker(sys.stdin.buffer, sys.stdout.buffer).run()
'''


def test_desktop_completion_reader_configures_completes_and_retires_through_the_real_helper(tmp_path):
    definition, path = desktop_spec(), tmp_path / "input.lock"
    adapter = ReadOnlyNativeTarget(argv=[sys.executable, "-u", "-c", HELPER], resource_path=path)
    assert not adapter._requires_presence(definition)
    with operation_scope(TaskOperation(definition, lambda: None, None)):
        reader = CompletionReader(adapter, definition)
        with reader.session():
            assert reader.observe() == OBSERVATION
        assert reader.retired
    witness = InputJournal(path).read()
    assert witness["owner"] is None and witness["held"] == {} and witness["in_flight"] is None


# (b) the exemption opens nothing beyond read-only verification.

@pytest.mark.parametrize("tool", ["AC_click_mouse", "AC_focus_window", "AC_write"])
def test_configured_desktop_reader_refuses_tools_and_focus_before_the_target(standard_desktop, tool):
    worker = ReadOnlyWorker(io.BytesIO(), io.BytesIO())
    configure(worker)
    with pytest.raises(AgentTaskError, match="read-only"):
        worker._dispatch("perform", {"tool": tool, "arguments": {}})
    assert worker._target.calls == [("ready", "local-desktop")]


def test_native_input_raised_inside_a_desktop_observation_is_refused_and_never_sent(standard_desktop):
    from je_auto_control.wrapper._input_observer import input_event
    sink = io.BytesIO()
    worker = ReadOnlyWorker(io.BytesIO(), sink)
    configure(worker)
    FakeDesktop.observe_hook = staticmethod(lambda: input_event("mouse_press", x=1, y=2, keycode=1))
    with pytest.raises(AgentTaskError, match="acknowledge native input"):
        worker._dispatch("observe", {})
    assert sink.getvalue() == b""


def test_focus_switch_requested_inside_a_desktop_observation_is_refused(standard_desktop, monkeypatch):
    from je_auto_control.utils.executor.action_executor import executor
    from je_auto_control.utils.tool_use_schema import run_tool_call
    focus = Mock(side_effect=AssertionError("focus switched"))
    monkeypatch.setitem(executor.event_dict, "AC_focus_window", focus)
    worker = ReadOnlyWorker(io.BytesIO(), io.BytesIO())
    configure(worker)
    FakeDesktop.observe_hook = staticmethod(lambda: run_tool_call("AC_focus_window", {"window_title": "x"}))
    with pytest.raises(AgentTaskError, match="read-only observation cannot dispatch"):
        worker._dispatch("observe", {})
    focus.assert_not_called()


@pytest.mark.parametrize("extra", [{"presence": {"token": "x"}}, {"presence_endpoint": {"pipe": "x"}}])
def test_readonly_worker_never_accepts_a_presence_lease(standard_desktop, extra):
    worker = ReadOnlyWorker(io.BytesIO(), io.BytesIO())
    with pytest.raises(AgentTaskError, match="read-only"):
        configure(worker, **extra)
    assert worker._spec is None and worker._presence_binding is None


def test_readonly_worker_refuses_cleanup_input_and_activity_readiness_on_a_desktop_scope(standard_desktop):
    worker = ReadOnlyWorker(io.BytesIO(), io.BytesIO())
    configure(worker)
    with pytest.raises(AgentTaskError, match="cleanup input"):
        worker._dispatch("cleanup", {"keys": [{"keycode": 65, "is_shift": False}], "buttons": []})
    with pytest.raises(AgentTaskError, match="presence"):
        worker._ready_activity()
    assert ("cleanup",) not in worker._target.calls


def test_a_readonly_subclass_that_reopens_an_input_path_loses_the_exemption(standard_desktop):
    class Reopened(ReadOnlyWorker):
        def _input(self, event):
            return None

    worker = Reopened(io.BytesIO(), io.BytesIO())
    with pytest.raises(AgentTaskError, match="requires a host presence binding"):
        configure(worker)
    assert worker._target.calls == []


# (c) every other worker still requires the presence binding.

def test_standard_native_worker_still_requires_a_presence_binding(standard_desktop):
    worker = NativeWorker(io.BytesIO(), io.BytesIO())
    with pytest.raises(AgentTaskError, match="requires a host presence binding"):
        configure(worker)
    assert worker._target.calls == []


def test_other_native_worker_subclasses_still_require_a_presence_binding(standard_desktop):
    class Other(NativeWorker):
        pass

    with pytest.raises(AgentTaskError, match="requires a host presence binding"):
        configure(Other(io.BytesIO(), io.BytesIO()))


def test_host_still_binds_presence_for_the_standard_desktop_worker_only():
    definition = desktop_spec()
    assert NativeDesktopTarget()._requires_presence(definition)
    assert not ReadOnlyNativeTarget()._requires_presence(definition)
