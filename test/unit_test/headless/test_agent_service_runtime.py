"""Verify managed service evidence using a real runtime and injected SCM functions."""
from concurrent.futures import CancelledError
from dataclasses import replace
import threading

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime.context import TaskOperation, operation_scope
from je_auto_control.utils.agent_runtime.errors import AgentEffectUnknown, AgentObservationStale, AgentTaskError
from je_auto_control.utils.agent_runtime.policy import TaskPolicy
from je_auto_control.utils.agent_runtime.service_observation import ServiceObservation, ServiceReceipt
from je_auto_control.utils.agent_runtime.service_operations import ServiceAcceptance
from je_auto_control.utils.agent_runtime.service_status import ServiceStatus
from je_auto_control.utils.agent_runtime.service_target import ManagedServiceTarget
from je_auto_control.utils.agent_runtime.service_verification import service_matches, validate_service_clause
from je_auto_control.utils.agent_runtime.target_dispatch import observe
from je_auto_control.utils.agent_runtime.verification import verify_clauses
from je_auto_control.utils.rbac.authorization import AuthorizationContext
from .test_agent_service_control import ControlApi, START, STOP

CLAUSE = {"kind": "service_state", "tool": "AC_service_start", "state": "running"}


def spec(**changes):
    value = AgentTaskSpec(goal="start reviewed service", target="service-fixture",
                         allowed_tools=("AC_service_start", "AC_service_stop"), success_criteria=(CLAUSE,))
    return replace(value, **changes)


def fixture():
    api = ControlApi()
    api.state = 1
    target = ManagedServiceTarget("service-fixture", "a" * 64, "local-service-fixture", api.controller(),
                                  allowed=frozenset({START, STOP}))
    return api, target


def action(runtime, task, frame, tool="AC_service_start"):
    return runtime.act(task, {"tool": tool, "arguments": {}, "observation_id": frame.observation_id})


@pytest.mark.parametrize("tool,state,expected", [("AC_service_start", 4, "passed"),
                                                ("AC_service_start", 1, "failed"),
                                                ("AC_service_stop", 1, "passed"),
                                                ("AC_service_stop", 4, "failed")])
def test_runtime_distinguishes_acceptance_from_independent_state(tmp_path, tool, state, expected):
    api, target = fixture()
    api.state = 1 if tool == "AC_service_start" else 4

    def start(*_):
        api.state = state
        return 1

    native = api.StartServiceW if tool == "AC_service_start" else api.ControlService
    native.call = start
    runtime = AgentRuntime(tmp_path / "runtime.db", targets={"service-fixture": target})
    try:
        desired = "running" if tool == "AC_service_start" else "stopped"
        clause = {"kind": "service_state", "tool": tool, "state": desired}
        task = runtime.submit(spec(success_criteria=(clause,))).task_id
        frame = runtime.observe(task)
        result = action(runtime, task, frame, tool)
        assert result.result["accepted"] is True
        assert "completed" not in result.result
        runtime.finish(task)
        row = runtime.store.get(task)
        assert row["verification"] == [{"kind": "service_state", "status": expected}]
        assert row["state"] == ("succeeded" if expected == "passed" else "waiting_user")
        assert api.OpenServiceW.calls == [(101, "OwnedFixture", 0x34)]
        assert len(api.QueryServiceStatusEx.calls) >= 4
    finally:
        runtime.close()


def test_effect_with_lost_acceptance_stays_uncertain(tmp_path):
    api, target = fixture()

    def start(*_):
        api.state = 4
        return 0

    api.StartServiceW.call = start
    runtime = AgentRuntime(tmp_path / "runtime.db", targets={"service-fixture": target})
    try:
        task = runtime.submit(spec()).task_id
        frame = runtime.observe(task)
        with pytest.raises(AgentEffectUnknown):
            action(runtime, task, frame)
        assert api.state == 4
        assert runtime.store.actions(task)[0]["status"] == "uncertain"
        assert runtime.get(task).state == "waiting_user"
        with pytest.raises(AgentTaskError):
            action(runtime, task, frame)
        assert len(api.StartServiceW.calls) == 1
    finally:
        runtime.close()


def test_runtime_refuses_changed_state_before_dispatch(tmp_path):
    api, target = fixture()
    runtime = AgentRuntime(tmp_path / "runtime.db", targets={"service-fixture": target})
    try:
        task = runtime.submit(spec()).task_id
        frame = runtime.observe(task)
        api.state = 4
        with pytest.raises(AgentObservationStale):
            action(runtime, task, frame)
        assert not api.StartServiceW.calls
        assert runtime.store.actions(task) == []
    finally:
        runtime.close()


def evidence():
    api, target = fixture()
    with operation_scope(TaskOperation(spec(), lambda: None, None)):
        target.ready(spec())
        before = target.observe()
        receipt = target.perform_observed("AC_service_start", {}, observation=before, operation_id="journal-1")
        api.state = 4
        current = target.observe()
    row = {"id": "journal-1", "command": "AC_service_start", "status": "confirmed",
           "grounding": {"service": before}, "result": receipt.to_dict()}
    target.cleanup()
    return row, current


@pytest.mark.parametrize("change", ["binding", "config", "scope", "target", "old_id", "old_time", "row_id",
                                    "receipt_operation", "receipt_binding", "before_binding", "uncertain"])
def test_completion_requires_same_attempt_and_new_capture(change):
    row, current = evidence()
    assert service_matches(CLAUSE, [row], current) is True
    if change in {"binding", "config", "scope", "target"}:
        key = {"binding": "binding_id", "config": "config_digest", "scope": "scope_id", "target": "target_id"}[change]
        current[key] = "b" * 64 if change == "config" else "other"
    elif change == "old_id":
        current["observation_id"] = row["grounding"]["service"]["observation_id"]
    elif change == "old_time":
        current["started"] = row["grounding"]["service"]["started"]
    elif change == "row_id":
        row["id"] = "another"
    elif change == "receipt_operation":
        row["result"]["operation"] = "stop"
    elif change == "receipt_binding":
        row["result"]["binding_id"] = "other"
    elif change == "before_binding":
        row["grounding"]["service"]["binding_id"] = "other"
    else:
        row["status"] = "uncertain"
    assert service_matches(CLAUSE, [row], current) is None


def test_latest_uncertain_attempt_prevents_old_confirmed_completion():
    row, current = evidence()
    newer = {**row, "id": "journal-2", "status": "uncertain"}
    assert service_matches(CLAUSE, [row, newer], current) is None


def test_wire_errors_become_unknown_verification():
    row, current = evidence()
    row["result"]["accepted"] = 1
    reports = verify_clauses([CLAUSE], TaskPolicy(spec()), [row], current)
    assert reports[0]["status"] == "unknown"


@pytest.mark.parametrize("changes", [{"kind": "semantic"}, {"state": "stopped"}, {"tool": "AC_service_restart"},
                                     {"service": "arbitrary"}, {"state": True}])
def test_invalid_criteria_cannot_expand_service_operations(changes):
    with pytest.raises(AgentTaskError):
        validate_service_clause({**CLAUSE, **changes})


def test_criterion_requires_task_tool_permission():
    with pytest.raises(AgentTaskError):
        TaskPolicy(spec(allowed_tools=("AC_service_stop",)))


@pytest.mark.parametrize("field,value", [("state", True), ("state", 4), ("state", "unknown"),
                                        ("controls_accepted", True), ("service_type", 0),
                                        ("win32_exit_code", -1), ("progress_checkpoint", 2**32),
                                        ("process_id", 0), ("process_id", True), ("consistency", "sequence_checked")])
def test_status_wire_refuses_invalid_diagnostics(field, value):
    row, _ = evidence()
    data = row["grounding"]["service"]["status"]
    data[field] = value
    with pytest.raises(AgentTaskError):
        ServiceStatus.from_dict(data)


def test_stopped_pid_and_extra_fields_are_rejected():
    row, current = evidence()
    data = row["grounding"]["service"]["status"]
    data["process_id"] = 123
    with pytest.raises(AgentTaskError):
        ServiceStatus.from_dict(data)
    with pytest.raises(AgentTaskError):
        ServiceObservation.from_dict({**current, "revision": 2})
    with pytest.raises(AgentTaskError):
        ServiceReceipt.from_dict({**row["result"], "completed": True})


def test_original_receipt_time_survives_exact_replay():
    api, target = fixture()
    with operation_scope(TaskOperation(spec(), lambda: None, None)):
        target.ready(spec())
        before = target.observe()
        first = target.perform_observed("AC_service_start", {}, observation=before, operation_id="journal-1")
        second = target.perform_observed("AC_service_start", {}, observation=before, operation_id="journal-1")
        assert first is second
        assert first.accepted_at == second.accepted_at
        with pytest.raises(AgentTaskError, match="conflicts"):
            target.perform_observed("AC_service_stop", {}, observation=before, operation_id="journal-1")
    assert len(api.StartServiceW.calls) == 1
    target.cleanup()


def test_cached_capture_cannot_enter_runtime_dispatch():
    _, target = fixture()
    with operation_scope(TaskOperation(spec(), lambda: None, None)):
        target.ready(spec())
        cached = target.observe()
        target.observe = lambda: cached
        with pytest.raises(AgentObservationStale):
            observe(target)
    target.cleanup()


def test_target_refuses_another_task_and_unmanaged_access():
    _, target = fixture()
    with pytest.raises(AgentTaskError):
        target.observe()
    with operation_scope(TaskOperation(spec(), lambda: None, None)):
        target.ready(spec())
    other = spec(goal="another task")
    with operation_scope(TaskOperation(other, lambda: None, None)):
        with pytest.raises(AgentTaskError):
            target.ready(other)
        with pytest.raises(AgentTaskError):
            target.observe()
    target.cleanup()


def test_cleanup_from_checkpoint_never_publishes():
    api, target = fixture()
    retiring = [False]

    def check():
        if retiring[0]:
            target.cleanup()

    with operation_scope(TaskOperation(spec(), check, None)):
        target.ready(spec())
        target.observe()
        retiring[0] = True
        with pytest.raises(AgentTaskError):
            target.observe()
    assert api.closed == [202, 101]


def test_post_dispatch_cancellation_preserved():
    api, target = fixture()

    def check():
        if api.StartServiceW.calls:
            raise CancelledError()

    with operation_scope(TaskOperation(spec(), check, None)):
        target.ready(spec())
        before = target.observe()
        with pytest.raises(CancelledError):
            target.perform_observed("AC_service_start", {}, observation=before, operation_id="journal-1")
    assert len(api.StartServiceW.calls) == 1
    target.cleanup()


def test_unconfirmed_controller_receipt_never_confirms():
    _, target = fixture()
    target._controller.perform = lambda *args, **kwargs: ServiceAcceptance("wrong", START)
    with operation_scope(TaskOperation(spec(), lambda: None, None)):
        target.ready(spec())
        before = target.observe()
        with pytest.raises(AgentEffectUnknown):
            target.perform_observed("AC_service_start", {}, observation=before, operation_id="journal-1")
    target.cleanup()


def test_failed_cleanup_remains_retryable():
    api, target = fixture()
    with operation_scope(TaskOperation(spec(), lambda: None, None)):
        target.ready(spec())
        target.observe()
    api.failed_close.add(101)
    with pytest.raises(AgentTaskError, match="cleanup_failed"):
        target.cleanup()
    api.failed_close.clear()
    target.cleanup()
    assert api.closed == [202, 101, 101]


def test_concurrent_cleanup_rejects_late_observation():
    api, target = fixture()
    entered, release = threading.Event(), threading.Event()
    original = api.query
    outcomes = []

    def blocked(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    def read():
        with operation_scope(TaskOperation(spec(), lambda: None, None)):
            target.ready(spec())
            try:
                outcomes.append(target.observe())
            except AgentTaskError:
                outcomes.append("retired")

    api.QueryServiceStatusEx.call = blocked
    worker = threading.Thread(target=read)
    closer = threading.Thread(target=target.cleanup)
    worker.start()
    try:
        assert entered.wait(2)
        closer.start()
        assert target._terminal.wait(2)
    finally:
        release.set()
        worker.join(3)
        if closer.ident is not None:
            closer.join(3)
    assert not worker.is_alive() and not closer.is_alive()
    assert outcomes == ["retired"]
    assert api.closed == [202, 101]


def test_reentrant_perform_cannot_replace_original_receipt_time():
    api, target = fixture()
    expected = [None]
    checks = [0]

    def check():
        if expected[0] is not None:
            checks[0] += 1
            if checks[0] == 2:
                with pytest.raises(AgentTaskError, match="reentrant"):
                    target.perform_observed("AC_service_start", {}, observation=expected[0], operation_id="journal-1")

    with operation_scope(TaskOperation(spec(), check, None)):
        target.ready(spec())
        expected[0] = target.observe()
        first = target.perform_observed("AC_service_start", {}, observation=expected[0], operation_id="journal-1")
        again = target.perform_observed("AC_service_start", {}, observation=expected[0], operation_id="journal-1")
        assert first is again and first.accepted_at == again.accepted_at
    assert len(api.StartServiceW.calls) == 1
    target.cleanup()


def test_same_user_from_another_authority_store_is_refused():
    _, target = fixture()
    first = AuthorizationContext("operator", "operator", store_path="first")
    second = AuthorizationContext("operator", "operator", store_path="second")
    with operation_scope(TaskOperation(spec(), lambda: None, first)):
        target.ready(spec())
    with operation_scope(TaskOperation(spec(), lambda: None, second)):
        with pytest.raises(AgentTaskError):
            target.observe()
        with pytest.raises(AgentTaskError):
            target.ready(spec())
    target.cleanup()


def test_checkpoint_cannot_replace_current_operation():
    _, target = fixture()
    swap = [False]
    nested = [None]

    def check():
        if swap[0]:
            nested[0] = operation_scope(TaskOperation(spec(), lambda: None, None))
            nested[0].__enter__()

    with operation_scope(TaskOperation(spec(), check, None)):
        target.ready(spec())
        swap[0] = True
        try:
            with pytest.raises(AgentTaskError):
                target.observe()
        finally:
            nested[0].__exit__(None, None, None)
    target.cleanup()


@pytest.mark.parametrize("field,value", [("service_version", True), ("service_version", 2),
                                        ("config_digest", "not-a-digest"), ("started", True),
                                        ("finished", float("inf")), ("consistency", "sequence_checked")])
def test_service_observation_schema_is_closed(field, value):
    _, current = evidence()
    with pytest.raises(AgentTaskError):
        ServiceObservation.from_dict({**current, field: value})
