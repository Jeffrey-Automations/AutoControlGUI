"""Complete fixture operations through real reader logic without native process inspection."""
from dataclasses import replace
import importlib.util
from pathlib import Path

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime.context import TaskOperation, operation_scope
from je_auto_control.utils.agent_runtime.errors import AgentEffectUnknown, AgentObservationStale, AgentTaskError
from je_auto_control.utils.agent_runtime.fixture_commands import FIXTURE_COMMAND, FixtureCommands
from je_auto_control.utils.agent_runtime.memory_target import MemoryBinding, MemorySemanticTarget
from je_auto_control.utils.agent_runtime.semantic_target import SemanticSnapshot
from je_auto_control.utils.process_memory.fixture_probe import FixtureBinding
from je_auto_control.utils.process_memory.models import ProcessIdentity
from je_auto_control.utils.process_memory.reader import ProcessMemoryReader

_spec = importlib.util.spec_from_file_location(
    "fixture_support", Path(__file__).with_name("test_process_memory_fixture.py"))
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)
fixture = _support.fixture_module


class Control:
    def __init__(self, state):
        self.state = state
        self.calls = []
        self.closed = 0
        self.before = lambda: None
        self.transform = lambda value: value
        self.fail_close = False

    def request(self, payload, *, timeout, checkpoint):
        assert 0 < timeout <= 1
        checkpoint()
        self.calls.append(payload)
        self.before()
        return self.transform(fixture._dispatch(self.state, payload))

    def close(self):
        self.closed += 1
        if self.fail_close:
            raise OSError("close pending")


def setup():
    state = fixture.FixtureState(_support.CHALLENGE)
    bootstrap = state.bootstrap()
    identity = ProcessIdentity("host", "session", bootstrap["pid"], 1, "fixture", "1", "x64", 64)
    probe = FixtureBinding.from_bootstrap(_support.CHALLENGE, bootstrap).probe("fixture")
    binding = MemoryBinding("fixture", identity, probe, ("document_id", "job_status"))
    control = Control(state)
    commands = FixtureCommands(binding, bootstrap["launch_nonce"], control)
    reader = ProcessMemoryReader(_support._OwnBuffers(state, identity))
    target = MemorySemanticTarget(binding, reader, commands)
    spec = AgentTaskSpec(goal="complete fixture job", target="fixture", allowed_tools=(FIXTURE_COMMAND,),
                         success_criteria=({"kind": "semantic", "tool": FIXTURE_COMMAND,
                                            "fields": {"document_id": 42, "job_status": "done"}},))
    return state, target, control, commands, spec


def test_full_reader_operation_and_completion(tmp_path):
    state, target, control, _, spec = setup()
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target})
    try:
        task = runtime.submit(spec).task_id
        frame = runtime.observe(task)
        result = runtime.act(task, {"tool": FIXTURE_COMMAND, "observation_id": frame.observation_id,
                                   "arguments": {"document_id": 42, "job_status": "done"}})
        assert result.result["comparison"] == "atomic"
        assert control.calls[0]["operation_id"] == result.action_id
        assert runtime.finish(task).state == "succeeded"
        assert state.snapshot()["sequence"] == 2
        assert control.closed >= 1
    finally:
        runtime.close()


def test_race_at_commit_refuses_without_overwriting_new_state():
    state, target, control, _, spec = setup()
    with operation_scope(TaskOperation(spec, lambda: None, None)):
        target.ready(spec)
        expected = SemanticSnapshot.from_dict(target.observe())
        control.before = lambda: state.set_state(99, "busy")
        with pytest.raises(AgentObservationStale):
            target.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                     expected=expected, operation_id="op-1")
    assert state.snapshot()["document_id"] == 99 and state.snapshot()["sequence"] == 2


def test_lost_reply_keeps_effect_uncertain_and_never_retries(tmp_path):
    state, target, control, _, spec = setup()

    def lose(_reply):
        raise OSError("PRIVATE transport data")

    control.transform = lose
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target})
    try:
        task = runtime.submit(spec).task_id
        frame = runtime.observe(task)
        with pytest.raises(AgentEffectUnknown) as error:
            runtime.act(task, {"tool": FIXTURE_COMMAND, "observation_id": frame.observation_id,
                              "arguments": {"document_id": 42, "job_status": "done"}})
        assert "PRIVATE" not in str(error.value)
        assert runtime.store.actions(task)[0]["status"] == "uncertain"
        assert state.snapshot()["document_id"] == 42 and len(control.calls) == 1
    finally:
        runtime.close()


@pytest.mark.parametrize("changes", [
    {"operation_id": "other"}, {"launch_nonce": "0" * 32}, {"sequence": 4},
    {"document_id": True}, {"job_status": "busy"}, {"address": 123},
    {"comparison": "non_atomic"}, {"kind": "snapshot"},
])
def test_unconfirmed_receipt_disables_further_commands(changes):
    _, target, control, commands, spec = setup()
    with operation_scope(TaskOperation(spec, lambda: None, None)):
        target.ready(spec)
        expected = SemanticSnapshot.from_dict(target.observe())
        control.transform = lambda reply: reply | changes
        with pytest.raises(AgentEffectUnknown):
            commands.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                      expected=expected, operation_id="op-1")
        with pytest.raises(AgentTaskError, match="live"):
            commands.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                      expected=expected, operation_id="op-1")
    assert len(control.calls) == 1


def test_original_operation_replay_does_not_repeat_effect():
    state, target, control, commands, spec = setup()
    with operation_scope(TaskOperation(spec, lambda: None, None)):
        target.ready(spec)
        expected = SemanticSnapshot.from_dict(target.observe())
        first = commands.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                           expected=expected, operation_id="op-1")
        second = commands.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                            expected=expected, operation_id="op-1")
    assert first == second and state.snapshot()["sequence"] == 2
    assert len(control.calls) == 2


def test_foreign_provenance_and_bad_arguments_never_send():
    _, target, control, commands, spec = setup()
    with operation_scope(TaskOperation(spec, lambda: None, None)):
        target.ready(spec)
        expected = SemanticSnapshot.from_dict(target.observe())
        with pytest.raises(AgentObservationStale):
            commands.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                      expected=replace(expected, identity_digest="foreign"), operation_id="op-1")
        with pytest.raises(AgentTaskError):
            commands.perform_grounded(FIXTURE_COMMAND, {"document_id": True, "job_status": "done"},
                                      expected=expected, operation_id="op-1")
    assert control.calls == []


def test_cleanup_is_terminal_even_when_close_requires_retry():
    _, _, control, commands, spec = setup()
    control.fail_close = True
    with pytest.raises(OSError):
        commands.cleanup()
    with pytest.raises(AgentTaskError, match="retired"):
        commands.ready(spec)
    control.fail_close = False
    commands.cleanup()
    assert control.closed == 2


def test_async_cancellation_retires_command_owner():
    from asyncio import CancelledError
    _, target, control, commands, spec = setup()

    def cancel(_reply):
        raise CancelledError()

    with operation_scope(TaskOperation(spec, lambda: None, None)):
        target.ready(spec)
        expected = SemanticSnapshot.from_dict(target.observe())
        control.transform = cancel
        with pytest.raises(CancelledError):
            commands.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                      expected=expected, operation_id="op-1")
        with pytest.raises(AgentTaskError, match="live"):
            commands.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                      expected=expected, operation_id="op-2")
    assert len(control.calls) == 1


def test_exhausted_sequence_never_sends_or_confirms_impossible_success():
    _, target, control, commands, spec = setup()
    with operation_scope(TaskOperation(spec, lambda: None, None)):
        target.ready(spec)
        expected = replace(SemanticSnapshot.from_dict(target.observe()), revision=2**64 - 2)
        with pytest.raises(AgentTaskError, match="exhausted"):
            commands.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                      expected=expected, operation_id="op-1")
    assert control.calls == []


def test_private_transport_task_error_is_not_treated_as_authority_failure():
    _, target, control, commands, spec = setup()

    def fail(_reply):
        raise AgentTaskError("PRIVATE transport contents")

    with operation_scope(TaskOperation(spec, lambda: None, None)):
        target.ready(spec)
        expected = SemanticSnapshot.from_dict(target.observe())
        control.transform = fail
        with pytest.raises(AgentEffectUnknown) as error:
            commands.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                      expected=expected, operation_id="op-1")
    assert "PRIVATE" not in str(error.value)


def test_checkpoint_failure_survives_transport_swallowing():
    _, target, control, commands, spec = setup()
    revoked = False

    def checkpoint():
        if revoked:
            raise AgentTaskError("authority revoked")

    def swallow(payload, *, timeout, checkpoint):
        nonlocal revoked
        revoked = True
        try:
            checkpoint()
        except AgentTaskError:
            pass
        return {}

    with operation_scope(TaskOperation(spec, checkpoint, None)):
        target.ready(spec)
        expected = SemanticSnapshot.from_dict(target.observe())
        control.request = swallow
        with pytest.raises(AgentTaskError, match="authority revoked"):
            commands.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                      expected=expected, operation_id="op-1")
    with pytest.raises(AgentTaskError, match="retired"):
        commands.ready(spec)
