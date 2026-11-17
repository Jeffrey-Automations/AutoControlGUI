"""Verify semantic helper scope, input refusal, deadlines and actual process retirement."""
from io import BytesIO
from pathlib import Path
import sys
import threading
import time

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskError
from je_auto_control.utils.agent_runtime.errors import AgentEffectUnknown
from je_auto_control.utils.agent_runtime.native_worker import NativeWorker
from je_auto_control.utils.agent_runtime.semantic_native_target import NativeSemanticTarget
from je_auto_control.utils.agent_runtime.semantic_target import SemanticSnapshot, SemanticTarget, SemanticReceipt


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "semantic_helper.py"


def spec():
    return {"goal": "increment owned fixture", "target": "fixture", "allowed_tools": ["AC_increment"],
            "success_criteria": [{"kind": "result_equals", "key": "comparison", "value": "atomic"}],
            "budget": {"action_seconds": 1}}


def snapshot():
    return SemanticSnapshot(target_id="fixture", identity_digest="a" * 64, adapter_id="fixture-ipc",
        schema_version="1", source="fixture_protocol", fields=(("value", 0),), revision=0,
        consistency="sequence_checked", observation_id="first", started=0, finished=0)


@pytest.fixture
def managed(tmp_path):
    target = NativeSemanticTarget(argv=[sys.executable, "-u", str(FIXTURE)],
                                  resource_path=tmp_path / "fixture.lock")
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target})
    try:
        yield runtime, target
    finally:
        runtime.close()


def test_owned_helper_round_trip_and_retirement_without_presence(managed):
    runtime, target = managed
    task = runtime.submit(spec())
    frame = runtime.observe(task.task_id)
    channel = target._channel
    assert frame.data["fields"] == {"value": 0}
    result = runtime.act(task.task_id, {"tool": "AC_increment", "observation_id": frame.observation_id})
    assert result.result == {"operation_id": result.action_id, "comparison": "atomic", "result": {"value": 1}}
    assert runtime.observe(task.task_id).data["fields"] == {"value": 1}
    assert target._ledger.empty
    assert target.presence_status["state"] in {"not_bound", "not_supported"}
    assert runtime.pause(task.task_id).state == "paused"
    assert channel.retired and target._channel is None and target._resource is None


@pytest.mark.parametrize("no_effect,expected", [(False, "passed"), (True, "failed")])
def test_helper_completion_reads_state_independently_of_successful_reply(managed, no_effect, expected):
    runtime, target = managed
    criterion = {"kind": "semantic", "tool": "AC_increment", "fields": {"value": 1}}
    task = runtime.submit(spec() | {"success_criteria": [criterion]})
    frame = runtime.observe(task.task_id)
    channel = target._channel
    reply = runtime.act(task.task_id, {"tool": "AC_increment", "arguments": {"no_effect": no_effect},
                                      "observation_id": frame.observation_id})
    assert reply.result["result"]["value"] == 1
    result = runtime.finish(task.task_id)
    assert result.verification == ({"kind": "semantic", "status": expected},)
    assert result.state == ("succeeded" if expected == "passed" else "waiting_user")
    assert channel.retired


def test_restarted_helper_cannot_complete_against_previous_process_evidence(tmp_path):
    def adapter():
        return NativeSemanticTarget(argv=[sys.executable, "-u", str(FIXTURE)],
                                    resource_path=tmp_path / "fixture.lock")
    database = tmp_path / "runtime.sqlite"
    runtime = AgentRuntime(database, targets={"fixture": adapter()})
    criterion = {"kind": "semantic", "tool": "AC_increment", "fields": {"value": 1}}
    try:
        task = runtime.submit(spec() | {"success_criteria": [criterion]})
        frame = runtime.observe(task.task_id)
        runtime.act(task.task_id, {"tool": "AC_increment", "observation_id": frame.observation_id})
    finally:
        runtime.close()
    restored = AgentRuntime(database, targets={"fixture": adapter()})
    try:
        restored.resume(task.task_id)
        result = restored.finish(task.task_id)
        assert result.state == "waiting_user"
        assert result.verification == ({"kind": "semantic", "status": "unknown"},)
        assert len(restored.store.actions(task.task_id)) == 1
    finally:
        restored.close()


@pytest.mark.parametrize("fault", ["hang", "lose_reply", "input"])
def test_failed_helper_operation_stays_uncertain_and_does_not_replay(managed, fault):
    runtime, target = managed
    task = runtime.submit(spec())
    frame = runtime.observe(task.task_id)
    channel = target._channel
    expected_error = AgentEffectUnknown if fault == "lose_reply" else AgentTaskError
    with pytest.raises(expected_error):
        runtime.act(task.task_id, {"tool": "AC_increment", "arguments": {fault: True},
                                  "observation_id": frame.observation_id})
    assert runtime.store.actions(task.task_id)[0]["status"] == "uncertain"
    assert target._ledger.empty
    with pytest.raises(AgentTaskError):
        runtime.act(task.task_id, {"tool": "AC_increment", "observation_id": frame.observation_id})
    runtime.cancel(task.task_id)
    assert channel.retired


def test_cancel_retires_a_helper_after_it_entered_a_blocked_command(tmp_path):
    marker = tmp_path / "entered.txt"
    target = NativeSemanticTarget(argv=[sys.executable, "-u", str(FIXTURE), str(marker)],
                                  resource_path=tmp_path / "fixture.lock")
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target})
    failures = []
    worker = None
    try:
        task = runtime.submit(spec() | {"budget": {"action_seconds": 20}})
        frame = runtime.observe(task.task_id)
        channel = target._channel
        def blocked():
            try:
                runtime.act(task.task_id, {"tool": "AC_increment", "arguments": {"hang": True},
                                          "observation_id": frame.observation_id})
            except Exception as error:
                failures.append(error)
        worker = threading.Thread(target=blocked)
        worker.start()
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        assert marker.read_text(encoding="utf-8") == "entered"
        runtime.cancel(task.task_id)
        worker.join(timeout=5)
        assert not worker.is_alive() and len(failures) == 1
        assert channel.retired and runtime.get(task.task_id).state == "cancelled"
        assert runtime.store.actions(task.task_id)[0]["status"] == "uncertain"
    finally:
        runtime.close()
        if worker is not None:
            worker.join(timeout=5)


class WorkerTarget(SemanticTarget):
    def __init__(self):
        self.calls = 0
        self.cleaned = 0

    def ready(self, _spec):
        return True, ""

    def perform_grounded(self, name, arguments, *, expected, operation_id):
        self.calls += 1
        return SemanticReceipt(operation_id, "atomic", {})

    def cleanup(self):
        self.cleaned += 1


def configured():
    target = WorkerTarget()
    worker = NativeWorker(BytesIO(), BytesIO(), target=target)
    worker._dispatch("configure", {"spec": spec(), "owner": {}})
    return worker, target


def request():
    return {"tool": "AC_increment", "arguments": {}, "expected": snapshot().to_dict(), "operation_id": "action"}


def test_worker_rechecks_tool_scope_without_relying_on_host_dispatch():
    worker, target = configured()
    with pytest.raises(AgentTaskError):
        worker._dispatch("perform_grounded", request() | {"tool": "AC_shell_command"})
    with pytest.raises(AgentTaskError):
        worker._dispatch("perform", {"tool": "AC_increment", "arguments": {}})
    assert target.calls == 0
    assert worker._dispatch("perform_grounded", request())["operation_id"] == "action"
    assert target.calls == 1


def test_worker_rejects_input_even_when_cleanup_is_active():
    worker, target = configured()
    worker._cleanup = True
    with pytest.raises(AgentTaskError, match="input"):
        worker._input({"kind": "key_release"})
    with pytest.raises(AgentTaskError, match="input"):
        worker._dispatch("cleanup", {"keys": [{"keycode": 65}], "buttons": []})
    assert target.cleaned == 0
    assert worker._dispatch("cleanup", {"keys": [], "buttons": []}) == {"cleaned": True}
    assert target.cleaned == 1


@pytest.mark.parametrize("path", ["cleanup", "close", "eof"])
@pytest.mark.parametrize("attempt", ["input", "command"])
def test_cleanup_callbacks_cannot_bypass_input_or_command_guards(path, attempt):
    from je_auto_control.wrapper._input_observer import input_event
    from je_auto_control.utils.executor.dispatch import dispatch_checkpoint
    worker, target = configured()
    effects = []
    def unsafe_cleanup():
        if attempt == "input":
            input_event("key_press", keycode=65, is_shift=False)
        else:
            dispatch_checkpoint("AC_increment", {})
        effects.append("would execute")
    target.cleanup = unsafe_cleanup
    operation = {"cleanup": lambda: worker._dispatch("cleanup", {"keys": [], "buttons": []}),
                 "close": worker.close, "eof": worker.run}[path]
    with pytest.raises(AgentTaskError):
        operation()
    assert effects == []


@pytest.mark.parametrize("changes", [{"operation_id": ""}, {"operation_id": None},
                                      {"expected": {}}, {"arguments": []}, {"extra": True}])
def test_worker_refuses_malformed_requests_before_adapter_dispatch(changes):
    worker, target = configured()
    with pytest.raises(AgentTaskError):
        worker._dispatch("perform_grounded", request() | changes)
    assert target.calls == 0


def test_host_refuses_legacy_dispatch_and_input_without_opening_a_helper(tmp_path):
    target = NativeSemanticTarget(argv=[sys.executable, "-u", str(FIXTURE)], resource_path=tmp_path / "fixture.lock")
    with pytest.raises(AgentTaskError, match="grounded"):
        target.perform("AC_increment", {})
    with pytest.raises(AgentTaskError, match="input"):
        target._input({"kind": "key_release"}, cleanup=True)
    assert target._channel is None


def test_host_refuses_legacy_protocol_before_configuring_target(tmp_path, monkeypatch):
    from je_auto_control.utils.agent_runtime import native_target
    calls = []
    class Channel:
        retired = False
        def request(self, operation, payload, **kwargs):
            calls.append(operation)
            return {"protocol": 1}
        def close(self):
            self.retired = True
    channel = Channel()
    monkeypatch.setattr(native_target, "owned_channel", lambda *args, **kwargs: channel)
    adapter = NativeSemanticTarget(argv=["reviewed-helper"], resource_path=tmp_path / "fixture.lock")
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": adapter})
    try:
        task = runtime.submit(spec())
        with pytest.raises(AgentTaskError, match="bootstrap"):
            runtime.observe(task.task_id)
        assert calls == ["bootstrap"] and channel.retired
    finally:
        runtime.close()


@pytest.mark.parametrize("unconfirmed", [{"cleaned": False}, {"cleaned": 1},
                                          {"cleaned": True, "extra": 0}, None])
def test_failed_cleanup_keeps_helper_owned_until_confirmation(tmp_path, unconfirmed):
    class Channel:
        retired = False
        response = {"cleaned": False}
        def request(self, operation, payload, **kwargs):
            return self.response
        def close(self):
            self.retired = True
    adapter = NativeSemanticTarget(argv=["reviewed-helper"], resource_path=tmp_path / "fixture.lock")
    channel = Channel()
    channel.response = unconfirmed
    adapter._channel = channel
    with pytest.raises(AgentTaskError, match="cleanup"):
        adapter.cleanup()
    assert adapter._channel is channel and not channel.retired
    channel.response = {"cleaned": True}
    adapter.cleanup()
    assert adapter._channel is None and channel.retired
