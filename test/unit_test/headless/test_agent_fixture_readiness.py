"""Claim fixture task ownership before lazy startup, including the existing helper path."""
from dataclasses import replace
from pathlib import Path
import sys
import threading

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime.context import TaskOperation, operation_scope
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.fixture_commands import FIXTURE_COMMAND
from je_auto_control.utils.agent_runtime.semantic_native_target import NativeSemanticTarget
from je_auto_control.utils.exception.control_signals import OperationCancelledError
from je_auto_control.utils.process_memory.models import MemoryObservationError
from je_auto_control.utils.rbac.authorization import AuthorizationContext
from headless.test_agent_fixture_target import setup


HELPER = Path(__file__).resolve().parents[2] / "fixtures" / "memory_target_helper.py"


def spec():
    return AgentTaskSpec(goal="complete fixture", target="fixture", allowed_tools=(FIXTURE_COMMAND,),
                         success_criteria=({"kind": "semantic", "tool": FIXTURE_COMMAND,
                                            "fields": {"document_id": 42, "job_status": "done"}},))


@pytest.mark.parametrize("fault", ["unmanaged", "target", "tools", "different_context"])
def test_invalid_readiness_never_acquires_resources(fault):
    target, _, _, calls, *_ = setup()
    requested = spec()
    if fault == "target":
        requested = replace(requested, target="other")
    if fault == "tools":
        requested = replace(requested, allowed_tools=("AC_click_mouse",))
    context = replace(requested, goal="other task") if fault == "different_context" else requested
    operation = None if fault == "unmanaged" else TaskOperation(context, lambda: None, None)
    with operation_scope(operation), pytest.raises(AgentTaskError):
        target.ready(requested)
    assert calls == []
    target.cleanup()


def test_lazy_readiness_binds_owner_before_launch_and_is_idempotent():
    target, _, channel, calls, *_ = setup()
    requested = spec()
    owner = AuthorizationContext("alice", "admin", "alice-store")
    with operation_scope(TaskOperation(requested, lambda: None, owner)):
        assert target.ready(requested) == (True, "")
        assert target.ready(requested) == (True, "")
        assert target.observe()["fields"] == {"document_id": 7, "job_status": "ready"}
    assert len(calls) == 1
    for other in (AuthorizationContext("bob", "admin", "alice-store"),
                  AuthorizationContext("alice", "admin", "other-store")):
        with operation_scope(TaskOperation(requested, lambda: None, other)):
            with pytest.raises(AgentTaskError, match="different managed"):
                target.ready(requested)
    assert not channel.retired
    target.cleanup()


def test_cancel_during_lazy_start_retires_all_acquired_owners():
    target, _, channel, calls, _, lease, observer = setup()
    signal = OperationCancelledError("stop")

    def check():
        if calls:
            raise signal

    with operation_scope(TaskOperation(spec(), check, None)):
        with pytest.raises(OperationCancelledError) as caught:
            target.ready(spec())
    assert caught.value is signal and channel.retired
    assert not lease.pending_cleanup and not observer.pending_cleanup


def test_competing_ready_cannot_claim_published_target_before_original_owner_binds():
    target, *_ = setup()
    entered, release = threading.Event(), threading.Event()
    outcomes = []
    alice, bob = AuthorizationContext("alice", "admin"), AuthorizationContext("bob", "admin")

    original_start = target.start

    def start(**kwargs):
        result = original_start(**kwargs)
        entered.set()
        assert release.wait(5)
        return result

    def ready():
        with operation_scope(TaskOperation(spec(), lambda: None, alice)):
            outcomes.append(target.ready(spec()))

    target.start = start
    worker = threading.Thread(target=ready)
    worker.start()
    try:
        assert entered.wait(5)
        assert target._target is not None
        with operation_scope(TaskOperation(spec(), lambda: None, bob)):
            with pytest.raises(AgentTaskError, match="in progress"):
                target.ready(spec())
        release.set()
        worker.join(5)
        assert not worker.is_alive() and outcomes == [(True, "")]
        with operation_scope(TaskOperation(spec(), lambda: None, bob)):
            with pytest.raises(AgentTaskError, match="different managed"):
                target.ready(spec())
    finally:
        release.set()
        worker.join(5)
        target.cleanup()


def test_scope_change_during_startup_retires_the_acquired_fixture():
    target, _, channel, _, provider, lease, observer = setup()
    changed = operation_scope(TaskOperation(replace(spec(), goal="other"), lambda: None, None))

    def factory(_):
        changed.__enter__()
        return provider

    target._provider_factory = factory
    with operation_scope(TaskOperation(spec(), lambda: None, None)):
        try:
            with pytest.raises(AgentTaskError, match="scope changed"):
                target.ready(spec())
        finally:
            changed.__exit__(None, None, None)
    assert channel.retired and not lease.pending_cleanup and not observer.pending_cleanup


def helper(tmp_path, *, partial=False):
    argv = [sys.executable, "-u", str(HELPER)] + (["--partial-read"] if partial else [])
    target = NativeSemanticTarget(argv=argv, resource_path=tmp_path / "fixture.lock")
    return AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target}), target


def test_actual_helper_carries_guarded_memory_read_command_completion_and_retirement(tmp_path):
    runtime, proxy = helper(tmp_path)
    try:
        task = runtime.submit(spec()).task_id
        frame = runtime.observe(task)
        channel = proxy._channel
        assert frame.data["source"] == "process_memory"
        assert frame.data["fields"] == {"document_id": 7, "job_status": "ready"}
        assert "header_address" not in str(frame.data)
        runtime.act(task, {"tool": FIXTURE_COMMAND, "observation_id": frame.observation_id,
                          "arguments": {"document_id": 42, "job_status": "done"}})
        assert runtime.finish(task).state == "succeeded"
        assert channel.retired and channel._process.poll() is not None
    finally:
        runtime.close()


def test_actual_helper_preserves_memory_failure_reason(tmp_path):
    runtime, proxy = helper(tmp_path, partial=True)
    try:
        task = runtime.submit(spec()).task_id
        with pytest.raises(MemoryObservationError, match="partial_read"):
            runtime.observe(task)
        channel = proxy._channel
        runtime.cancel(task)
        assert channel.retired
    finally:
        runtime.close()


def test_helper_restart_cannot_reuse_synthetic_memory_identity(tmp_path):
    runtime, _ = helper(tmp_path)
    try:
        first = runtime.submit(spec()).task_id
        before = runtime.observe(first)
        runtime.cancel(first)
        second = runtime.submit(spec()).task_id
        after = runtime.observe(second)
        assert before.data["identity_digest"] != after.data["identity_digest"]
        assert after.data["fields"] == {"document_id": 7, "job_status": "ready"}
        runtime.cancel(second)
    finally:
        runtime.close()
