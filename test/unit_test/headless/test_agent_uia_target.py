"""Drive scoped UI observations through managed runtime and real hidden helper IPC."""
from pathlib import Path
import sys
import threading

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime.context import TaskOperation, operation_scope
from je_auto_control.utils.agent_runtime.errors import AgentObservationStale, AgentTaskError
from je_auto_control.utils.agent_runtime.semantic_native_target import NativeSemanticTarget
from je_auto_control.utils.agent_runtime import capture_checkpoint
from je_auto_control.utils.agent_runtime.uia_target import UIA_FIELDS, UIA_SELECTORS, UiaObservationTarget
from headless.test_agent_scoped_uia import Node, source


def target(mode="partial"):
    closed = []
    def acquire(check):
        check()
        root = Node().add(Node("1001", value="17"), Node("1002", value="ready"),
            Node("1003", value=""), Node("1004", enabled=False),
            Node("1005", value="synthetic-secret", password=mode != "complete"), Node("1006"))
        if mode != "complete":
            root.add(Node("1006"))
        reader, automation = source(root, UIA_SELECTORS)
        if mode == "hang":
            original = automation.ElementFromHandle
            def blocked(hwnd):
                threading.Event().wait(30)
                return original(hwnd)
            automation.ElementFromHandle = blocked
        return reader
    return UiaObservationTarget("fixture", acquire, lambda: closed.append(True)), closed


def spec():
    return {"goal": "inspect owned fixture", "target": "fixture", "allowed_tools": ["AC_fixture_set_state"],
            "success_criteria": [{"kind": "semantic", "tool": "AC_fixture_set_state",
                                  "fields": {"job_status": "ready"}}], "budget": {"action_seconds": 2}}


@pytest.mark.parametrize("mode,status", [("partial", "partial"), ("complete", "unverified")])
def test_runtime_publishes_values_but_refuses_actions_and_completion(tmp_path, mode, status):
    adapter, closed = target(mode)
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": adapter})
    try:
        task = runtime.submit(spec()).task_id
        frame = runtime.observe(task)
        assert frame.data["status"] == status
        with pytest.raises(AgentObservationStale):
            runtime.act(task, {"tool": "AC_fixture_set_state", "observation_id": frame.observation_id})
        result = runtime.finish(task)
        assert result.state == "waiting_user" and result.verification[0]["status"] == "unknown"
        assert runtime.store.actions(task) == []
    finally:
        runtime.close()
    assert closed


def test_unmanaged_target_never_acquires_and_cleanup_failure_can_retry():
    calls = []
    def acquire(_check):
        calls.append("acquire")
        pytest.fail("unmanaged acquisition")
    def close():
        calls.append("close")
        if len(calls) == 1:
            raise AgentTaskError("retirement pending")
    adapter = UiaObservationTarget("fixture", acquire, close)
    with pytest.raises(AgentTaskError):
        adapter.ready(AgentTaskSpec.from_dict(spec()))
    assert calls == []
    with pytest.raises(AgentTaskError, match="pending"):
        adapter.cleanup()
    adapter.cleanup()
    assert calls == ["close", "close"]


def test_cleanup_during_acquisition_prevents_late_source_publication():
    base, _ = target()
    closed = []
    def acquire(check):
        reader = base._acquire(check)
        adapter.cleanup()
        return reader
    adapter = UiaObservationTarget("fixture", acquire, lambda: closed.append(True))
    request = AgentTaskSpec.from_dict(spec())
    with operation_scope(TaskOperation(request, lambda: None, None)):
        with pytest.raises(AgentTaskError):
            adapter.ready(request)
    assert adapter._source is None and closed


def test_cleanup_during_contract_check_prevents_source_publication(monkeypatch):
    adapter, closed = target()
    from je_auto_control.utils.agent_runtime.scoped_uia import ScopedUiaSource
    def fields(_source):
        adapter.cleanup()
        return UIA_FIELDS
    monkeypatch.setattr(ScopedUiaSource, "field_scope", property(fields))
    request = AgentTaskSpec.from_dict(spec())
    with operation_scope(TaskOperation(request, lambda: None, None)):
        with pytest.raises(AgentTaskError):
            adapter.ready(request)
    assert adapter._source is None and closed


@pytest.mark.parametrize("interval", [0.0, 3600.0], ids=["every-call", "throttled"])
def test_revocation_during_capture_prevents_publication(monkeypatch, interval):
    # Full runtime checkpoints are throttled during the read-only capture, but the
    # unthrottled one after it still runs before anything is published.
    monkeypatch.setattr(capture_checkpoint, "INTERVAL", interval)
    adapter, _ = target("complete")
    request = AgentTaskSpec.from_dict(spec())
    state = {"checks": 0, "revoke_after": None}

    def checkpoint():
        state["checks"] += 1
        if state["revoke_after"] is not None and state["checks"] > state["revoke_after"]:
            raise AgentTaskError("authority revoked")

    with operation_scope(TaskOperation(request, checkpoint, None)):
        adapter.ready(request)
        state["revoke_after"] = state["checks"] + 2
        with pytest.raises(AgentTaskError, match="revoked"):
            adapter.observe()
    adapter.cleanup()


def test_throttled_capture_still_validates_scope_on_every_call(monkeypatch):
    monkeypatch.setattr(capture_checkpoint, "INTERVAL", 3600.0)
    adapter, _ = target("complete")
    request = AgentTaskSpec.from_dict(spec())
    full = []
    with operation_scope(TaskOperation(request, lambda: full.append(1), None)):
        adapter.ready(request)
        before = len(full)
        validated = []
        original = adapter._validate
        monkeypatch.setattr(adapter, "_validate", lambda operation: (validated.append(1), original(operation)))
        adapter.observe()
    # Start, one throttled capture check and the closing check run the full checkpoint;
    # every COM call in between still re-validates the pinned scope.
    assert len(full) - before == 3
    assert len(validated) > 50
    adapter.cleanup()


@pytest.mark.parametrize("mode", ["partial", "complete", "hang"])
def test_hidden_helper_preserves_partial_fields_and_retires_blocked_provider(tmp_path, mode):
    class Proxy(NativeSemanticTarget):
        observation_sources = ("uia",)
        observation_fields = UIA_FIELDS
    helper = Path(__file__).resolve().parents[2] / "fixtures" / "scoped_uia_helper.py"
    proxy = Proxy(argv=[sys.executable, "-u", str(helper), mode], resource_path=tmp_path / "uia.lock")
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": proxy})
    try:
        task = runtime.submit(spec()).task_id
        if mode == "hang":
            with pytest.raises(AgentTaskError):
                runtime.observe(task)
            assert proxy._channel is None or proxy._channel.retired
        else:
            frame = runtime.observe(task)
            channel = proxy._channel
            assert frame.data["status"] == ("partial" if mode == "partial" else "unverified")
            if mode == "partial":
                result = frame.data["sources"]["uia"]["partial"]
                assert result["fields"]["empty"] == "" and result["fields"]["enabled"] is False
                assert result["failures"] == {"password": "protected", "duplicate": "ambiguous"}
                assert "synthetic-secret" not in str(result)
            with pytest.raises(AgentObservationStale):
                runtime.act(task, {"tool": "AC_fixture_set_state", "observation_id": frame.observation_id})
            runtime.pause(task)
            assert channel.retired
    finally:
        runtime.close()


def test_native_factory_waits_for_managed_readiness_and_uses_bound_window(monkeypatch):
    from je_auto_control.utils.agent_runtime import uia_target
    from headless.test_agent_scoped_uia import Automation
    base, _ = target()
    original = base._acquire(lambda: None)
    calls = []
    automation = Automation(Node())
    def create():
        calls.append("COM")
        return automation
    monkeypatch.setattr(uia_target, "_native_automation", create)
    adapter = UiaObservationTarget.from_window_owner("fixture", lambda check: original._binding,
                                                     lambda: calls.append("closed"))
    assert calls == []
    request = AgentTaskSpec.from_dict(spec())
    with operation_scope(TaskOperation(request, lambda: None, None)):
        adapter.ready(request)
        assert calls == ["COM"]
        report = adapter.observe()
        assert report["status"] == "partial"
        assert set(report["sources"]["uia"]["partial"]["failures"]) == set(UIA_FIELDS)
    adapter.cleanup()
    assert calls == ["COM", "closed"]
