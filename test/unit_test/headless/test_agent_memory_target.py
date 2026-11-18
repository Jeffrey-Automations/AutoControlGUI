"""Exercise managed memory targets with the real reader and an owned synthetic provider."""
from contextlib import contextmanager
from dataclasses import replace
import importlib.util
from pathlib import Path

import pytest

from je_auto_control.utils.agent_runtime.context import TaskOperation, operation_scope
from je_auto_control.utils.agent_runtime.errors import AgentEffectUnknown, AgentObservationStale, AgentTaskError
from je_auto_control.utils.agent_runtime.memory_target import MemoryBinding, MemorySemanticTarget
from je_auto_control.utils.agent_runtime.models import AgentTaskSpec
from je_auto_control.utils.agent_runtime.semantic_target import SemanticReceipt, SemanticSnapshot, observe
from je_auto_control.utils.process_memory.models import FailureReason, MemoryObservationError, ReadPlan
from je_auto_control.utils.process_memory.reader import ProcessMemoryReader
_spec = importlib.util.spec_from_file_location(
    "memory_reader_support", Path(__file__).with_name("test_process_memory_reader.py"))
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)
ADDRESS, IDENTITY, SCHEMA = _support.ADDRESS, _support.IDENTITY, _support.SCHEMA
Handle, probe = _support.Handle, _support.probe


class Provider:
    def __init__(self):
        self.handle = Handle()
        self.opens = 0

    def open_readonly(self, _identity):
        self.opens += 1
        return self.handle


class Commands:
    def __init__(self):
        self.calls = []
        self.closed = 0
        self.error = None

    def ready(self, _spec):
        return True, ""

    def perform_grounded(self, name, arguments, *, expected, operation_id):
        self.calls.append((name, expected, operation_id))
        if self.error:
            raise self.error
        return SemanticReceipt(operation_id, "non_atomic", {"accepted": True})

    def cleanup(self):
        self.closed += 1


def setup_target():
    provider, commands = Provider(), Commands()
    # Reads here run under the managed runtime, whose every checkpoint is a durable write; the
    # reader's own 1 s default budget ran out on a loaded CI runner. Deadlines are tested elsewhere.
    reviewed = probe(resolve=lambda identity, view: ReadPlan(ADDRESS, SCHEMA.size, ADDRESS - 8), timeout=30.0)
    binding = MemoryBinding("fixture", IDENTITY, reviewed, ("document_id", "job_status"))
    target = MemorySemanticTarget(binding, ProcessMemoryReader(provider), commands)
    spec = AgentTaskSpec(goal="update document", target="fixture", allowed_tools=("AC_update",),
                         success_criteria=({"kind": "semantic", "tool": "AC_update",
                                            "fields": {"document_id": 42}},))
    return target, provider, commands, spec


@contextmanager
def managed(target, spec, checkpoint=lambda: None):
    with operation_scope(TaskOperation(spec, checkpoint, None)):
        assert target.ready(spec) == (True, "")
        yield


def test_real_reader_projection_and_original_dispatch_witness():
    target, provider, commands, spec = setup_target()
    with managed(target, spec):
        frame = observe(target)
        assert frame["fields"] == {"document_id": 17, "job_status": "ready"}
        assert frame["source"] == "process_memory" and frame["revision"] == 2
        expected = SemanticSnapshot.from_dict(frame)
        receipt = target.perform_grounded("AC_update", {}, expected=expected, operation_id="op-1")
        assert receipt.comparison == "non_atomic"
        assert commands.calls == [("AC_update", expected, "op-1")]
        assert provider.opens == 2 and provider.handle.closed == 2
    assert not {"pid", "address", "raw", "birth"} & frame.keys()


def test_no_scope_and_wrong_task_never_open_reader():
    target, provider, _, spec = setup_target()
    with pytest.raises(AgentTaskError):
        target.observe()
    with operation_scope(TaskOperation(replace(spec, target="other"), lambda: None, None)):
        with pytest.raises(AgentTaskError):
            target.ready(spec)
    with managed(target, spec):
        with operation_scope(TaskOperation(replace(spec, goal="another"), lambda: None, None)):
            with pytest.raises(AgentTaskError):
                target.observe()
    assert provider.opens == 0


def test_unknown_fields_refused_at_binding():
    with pytest.raises(MemoryObservationError) as error:
        MemoryBinding("fixture", IDENTITY, probe(), ("password",))
    assert error.value.reason == FailureReason.SCOPE_DENIED


def test_changed_revision_prevents_command():
    target, provider, commands, spec = setup_target()
    with managed(target, spec):
        expected = SemanticSnapshot.from_dict(target.observe())
        provider.handle.memory[ADDRESS - 8] = 4
        with pytest.raises(AgentObservationStale):
            target.perform_grounded("AC_update", {}, expected=expected, operation_id="op-1")
    assert commands.calls == []


def test_read_failure_preserves_reason_without_private_data():
    target, provider, _, spec = setup_target()
    provider.handle.transform = lambda value: value[:-1]
    with managed(target, spec), pytest.raises(MemoryObservationError) as error:
        target.observe()
    assert error.value.reason == FailureReason.PARTIAL_READ
    assert str(error.value) == "partial_read"
    assert provider.handle.closed == 1


def test_cancellation_during_read_retires_handle():
    target, provider, _, spec = setup_target()
    cancelled = False

    def checkpoint():
        if cancelled:
            raise AgentTaskError("revoked")

    def revoke():
        nonlocal cancelled
        cancelled = True

    provider.handle.after_read = revoke
    with managed(target, spec, checkpoint), pytest.raises(AgentTaskError, match="revoked"):
        target.observe()
    assert provider.handle.closed == 1


def test_cleanup_failure_retains_reader_and_terminal_state_until_retry():
    target, provider, commands, spec = setup_target()
    provider.handle.fail_close = True
    with managed(target, spec):
        with pytest.raises(MemoryObservationError):
            target.observe()
        with pytest.raises(MemoryObservationError):
            target.observe()
        assert provider.opens == 1
    with pytest.raises(MemoryObservationError) as error:
        target.cleanup()
    assert error.value.reason == FailureReason.CLEANUP_FAILED
    provider.handle.fail_close = False
    target.cleanup()
    assert commands.closed == 2 and provider.handle.closed == 3
    with operation_scope(TaskOperation(spec, lambda: None, None)):
        with pytest.raises(AgentTaskError):
            target.ready(spec)
        with pytest.raises(AgentTaskError):
            target.observe()


def test_policy_and_ungrounded_refusal_then_unknown_effect():
    target, provider, commands, spec = setup_target()
    with managed(target, spec):
        expected = SemanticSnapshot.from_dict(target.observe())
        with pytest.raises(AgentTaskError):
            target.perform("AC_update", {})
        with pytest.raises(AgentTaskError):
            target.perform_grounded("AC_other", {}, expected=expected, operation_id="op-1")
        assert provider.opens == 1 and commands.calls == []
        commands.error = AgentEffectUnknown("readback required")
        with pytest.raises(AgentEffectUnknown):
            target.perform_grounded("AC_update", {}, expected=expected, operation_id="op-2")
        assert len(commands.calls) == 1


def test_runtime_reads_applies_and_independently_verifies_memory(tmp_path):
    from je_auto_control.utils.agent_runtime import AgentRuntime
    target, provider, commands, spec = setup_target()

    def apply(name, arguments, *, expected, operation_id):
        assert expected.revision == 2
        data = SCHEMA.pack(42, b"done")
        provider.handle.memory.update({ADDRESS + i: byte for i, byte in enumerate(data)})
        provider.handle.memory[ADDRESS - 8] = 4
        commands.calls.append(operation_id)
        return SemanticReceipt(operation_id, "non_atomic", {"accepted": True})

    commands.perform_grounded = apply
    runtime = AgentRuntime(tmp_path / "memory.sqlite", targets={"fixture": target})
    try:
        task = runtime.submit(spec).task_id
        frame = runtime.observe(task)
        runtime.act(task, {"tool": "AC_update", "observation_id": frame.observation_id})
        result = runtime.finish(task)
        assert result.state == "succeeded"
        assert len(commands.calls) == 1
        assert provider.opens == 4
        assert provider.handle.closed == provider.opens
    finally:
        runtime.close()


@pytest.mark.parametrize("owner", [
    ("bob", "admin", "store-a"), ("alice", "viewer", "store-a"),
    ("alice", "admin", "store-b"), None,
])
def test_identical_task_cannot_borrow_another_owner_binding(owner):
    from je_auto_control.utils.rbac.authorization import AuthorizationContext
    target, provider, _, spec = setup_target()
    original = AuthorizationContext("alice", "admin", "store-a")
    with operation_scope(TaskOperation(spec, lambda: None, original)):
        target.ready(spec)
    replacement = AuthorizationContext(*owner) if owner else None
    with operation_scope(TaskOperation(spec, lambda: None, replacement)):
        with pytest.raises(AgentTaskError, match="owner"):
            target.ready(spec)
        with pytest.raises(AgentTaskError, match="owner"):
            target.observe()
    assert provider.opens == 0
