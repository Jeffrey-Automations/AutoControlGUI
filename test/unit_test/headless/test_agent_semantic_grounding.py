"""Exercise semantic freshness, revision fencing and uncertain receipts through the runtime."""
from dataclasses import replace
import time

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime.errors import AgentEffectUnknown, AgentObservationStale, AgentTaskError
from je_auto_control.utils.agent_runtime.semantic_target import (
    SemanticReceipt, SemanticSnapshot, SemanticTarget, fingerprint,
)
from je_auto_control.utils.process_memory.models import Observation


def snapshot(**changes):
    value = SemanticSnapshot(target_id="fixture", identity_digest="a" * 64, adapter_id="document",
                             schema_version="1", source="process_memory", fields=(("value", 0),),
                             revision=0, consistency="sequence_checked", observation_id="first",
                             started=1.0, finished=2.0)
    return replace(value, **changes)


class Target(SemanticTarget):
    def __init__(self):
        self.state = snapshot()
        self.reads = 0
        self.calls = []
        self.lose_reply = False

    def ready(self, _spec):
        return True, ""

    def observe(self):
        self.reads += 1
        now = time.monotonic()
        return replace(self.state, observation_id=f"read-{self.reads}",
                       started=now, finished=now).to_dict()

    def perform_grounded(self, name, arguments, *, expected, operation_id):
        if expected.grounding() != self.state.grounding():
            raise AgentObservationStale("changed at commit")
        self.calls.append((name, expected, operation_id))
        self.state = replace(self.state, revision=self.state.revision + 2, fields=(("value", 1),))
        if self.lose_reply:
            raise AgentEffectUnknown("readback required")
        return SemanticReceipt(operation_id, "atomic", {"value": 1})

    def cleanup(self):
        pass


@pytest.fixture
def managed(tmp_path):
    target = Target()
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target})
    spec = AgentTaskSpec(goal="increment", target="fixture", allowed_tools=("AC_increment",),
                         success_criteria=({"kind": "result_equals", "key": "value", "value": 1},))
    task = runtime.submit(spec)
    try:
        yield runtime, target, task.task_id
    finally:
        runtime.close()


def act(runtime, task, frame):
    return runtime.act(task, {"tool": "AC_increment", "observation_id": frame.observation_id})


def test_fresh_metadata_does_not_invalidate_identical_semantic_state(managed):
    runtime, target, task = managed
    frame = runtime.observe(task)
    result = act(runtime, task, frame)
    receipt = runtime.store.actions(task)[0]
    assert receipt["status"] == "confirmed"
    assert target.reads == 2
    name, expected, operation_id = target.calls[0]
    assert name == "AC_increment" and expected.observation_id == "read-1"
    assert operation_id == receipt["id"] == result.action_id
    assert expected.revision == 0
    assert result.result == {"operation_id": operation_id, "comparison": "atomic", "result": {"value": 1}}


@pytest.mark.parametrize("changes", [
    {"revision": 4}, {"fields": (("value", 9),)}, {"identity_digest": "b" * 64},
    {"target_id": "another"}, {"schema_version": "2"}, {"adapter_id": "different"},
    {"source": "dom"}, {"revision": None, "consistency": "best_effort"},
])
def test_changed_state_or_provenance_refuses_before_dispatch(managed, changes):
    runtime, target, task = managed
    frame = runtime.observe(task)
    target.state = replace(target.state, **changes)
    with pytest.raises(AgentObservationStale):
        act(runtime, task, frame)
    assert target.calls == [] and runtime.store.actions(task) == []


def test_unknown_effect_is_uncertain_and_cannot_replay_the_observation(managed):
    runtime, target, task = managed
    frame = runtime.observe(task)
    target.lose_reply = True
    with pytest.raises(AgentEffectUnknown):
        act(runtime, task, frame)
    assert target.state.fields == (("value", 1),)
    assert runtime.store.actions(task)[0]["status"] == "uncertain"
    assert runtime.get(task).state == "waiting_user"
    with pytest.raises(AgentTaskError):
        act(runtime, task, frame)
    assert len(target.calls) == 1


@pytest.mark.parametrize("reply", [{"status": "effect_unknown"}, SemanticReceipt("another", "atomic", {})])
def test_unconfirmed_or_wrong_operation_reply_is_never_confirmed(managed, reply):
    runtime, target, task = managed
    frame = runtime.observe(task)
    target.perform_grounded = lambda *args, **kwargs: reply
    with pytest.raises(AgentTaskError, match="confirm"):
        act(runtime, task, frame)
    assert runtime.store.actions(task)[0]["status"] == "uncertain"


def test_receipt_copies_values_and_explicitly_preserves_non_atomic_comparison():
    values = {"document": [1]}
    receipt = SemanticReceipt("operation", "non_atomic", values)
    values["document"].append(2)
    assert receipt.to_dict() == {"operation_id": "operation", "comparison": "non_atomic",
                                 "result": {"document": [1]}}
    assert SemanticReceipt.from_dict(receipt.to_dict()) == receipt


def test_task_tool_scope_is_checked_before_semantic_dispatch(managed):
    runtime, target, task = managed
    frame = runtime.observe(task)
    with pytest.raises(AgentTaskError):
        runtime.act(task, {"tool": "AC_shell_command", "observation_id": frame.observation_id})
    assert target.calls == []


def test_change_after_runtime_grounding_is_rejected_at_adapter_commit(managed):
    runtime, target, task = managed
    frame = runtime.observe(task)
    original = target.perform_grounded
    def changed_before_commit(*args, **kwargs):
        target.state = replace(target.state, revision=2)
        return original(*args, **kwargs)
    target.perform_grounded = changed_before_commit
    with pytest.raises(AgentObservationStale, match="commit"):
        act(runtime, task, frame)
    assert target.calls == [] and target.state.fields == (("value", 0),)
    assert runtime.store.actions(task)[0]["status"] == "uncertain"


def test_semantic_grounding_does_not_extend_observation_lifetime(managed):
    runtime, target, task = managed
    frame = runtime.observe(task)
    runtime._observation_times[task] -= 31
    with pytest.raises(AgentObservationStale, match="expired"):
        act(runtime, task, frame)
    assert target.calls == []


def test_cancelled_task_cannot_dispatch_a_semantic_command(managed):
    runtime, target, task = managed
    frame = runtime.observe(task)
    runtime.cancel(task)
    with pytest.raises(AgentTaskError):
        act(runtime, task, frame)
    assert target.calls == []


def test_unknown_helper_fields_never_become_public_observation(managed):
    runtime, target, task = managed
    target.observe = lambda: snapshot().to_dict() | {"raw_address": 4096}
    with pytest.raises(AgentTaskError, match="schema"):
        runtime.observe(task)
    assert runtime.store.actions(task) == [] and target.calls == []


def test_payload_cannot_opt_an_ordinary_target_into_semantic_grounding():
    ordinary = object()
    first = snapshot().to_dict()
    second = snapshot(observation_id="second", started=3.0, finished=4.0).to_dict()
    assert fingerprint(ordinary, first) != fingerprint(ordinary, second)
    assert fingerprint(Target(), first) == fingerprint(Target(), second)


@pytest.mark.parametrize("changes", [
    {"complete": False}, {"revision": True}, {"revision": -2}, {"revision": 1},
    {"revision": 2**64}, {"consistency": "unknown"}, {"consistency": "best_effort"},
    {"finished": float("nan")}, {"started": True}, {"started": 3.0},
    {"started": 10**400, "finished": 10**400}, {"finished": float("inf")},
    {"fields": {"value": b"raw"}}, {"fields": {"value": []}},
    {"fields": {"value": 2**63}}, {"fields": {}}, {"fields": {"bad key": 1}},
    {"fields": {"value": "x" * 65537}}, {"raw_address": 4096},
])
def test_invalid_helper_snapshots_fail_closed(changes):
    with pytest.raises(AgentTaskError):
        SemanticSnapshot.from_dict(snapshot().to_dict() | changes)


def test_reader_result_round_trip_preserves_revision_and_hides_semantic_values_from_repr():
    memory = Observation("read", "fixture", "a" * 64, "probe", "1", 1.0, 2.0,
                         (("job_status", "private-state"),), "sequence_checked", 72, 4, revision=8)
    result = SemanticSnapshot.from_memory(memory)
    assert result.revision == 8 and result.fields == memory.fields
    assert SemanticSnapshot.from_dict(result.to_dict()) == result
    assert "private-state" not in repr(result)
    assert set(result.to_dict()) == {"target_id", "identity_digest", "adapter_id", "schema_version", "source",
                                     "fields", "revision", "consistency", "complete", "observation_id",
                                     "started", "finished"}


def semantic_task(runtime, fields=None):
    return runtime.submit(AgentTaskSpec(
        goal="verify fixture independently", target="fixture", allowed_tools=("AC_increment",),
        success_criteria=({"kind": "semantic", "tool": "AC_increment",
                           "fields": {"value": 1} if fields is None else fields},))).task_id


def test_completion_uses_fresh_fields_and_durable_target_witness(managed):
    runtime, target, _task = managed
    task = semantic_task(runtime)
    frame = runtime.observe(task)
    act(runtime, task, frame)
    receipt = runtime.store.actions(task)[0]
    assert receipt["grounding"]["semantic"] == dict(frame.data)
    result = runtime.finish(task)
    assert result.state == "succeeded"
    assert result.verification == ({"kind": "semantic", "status": "passed"},)
    assert target.reads == 3


def test_successful_reply_without_the_effect_fails_independent_completion(managed):
    runtime, target, _task = managed
    task = semantic_task(runtime)
    target.perform_grounded = lambda *args, **kwargs: SemanticReceipt(kwargs["operation_id"], "atomic", {"value": 1})
    frame = runtime.observe(task)
    act(runtime, task, frame)
    result = runtime.finish(task)
    assert result.state == "waiting_user"
    assert result.verification == ({"kind": "semantic", "status": "failed"},)


@pytest.mark.parametrize("changes", [
    {"identity_digest": "b" * 64}, {"target_id": "another"}, {"adapter_id": "different"},
    {"schema_version": "2"}, {"source": "different"}, {"fields": (("missing", 1),)},
    {"revision": None, "consistency": "best_effort"},
])
def test_completion_cannot_reuse_evidence_from_another_target_or_partial_state(managed, changes):
    runtime, target, _task = managed
    task = semantic_task(runtime)
    frame = runtime.observe(task)
    act(runtime, task, frame)
    target.state = replace(target.state, **changes)
    result = runtime.finish(task)
    assert result.state == "waiting_user"
    assert result.verification == ({"kind": "semantic", "status": "unknown"},)


def test_replayed_snapshot_is_not_independent_completion(managed):
    runtime, target, _task = managed
    task = semantic_task(runtime, {"value": 0})
    frame = runtime.observe(task)
    act(runtime, task, frame)
    target.observe = lambda: dict(frame.data)
    with pytest.raises(AgentObservationStale, match="current read"):
        runtime.finish(task)
    assert runtime.get(task).state != "succeeded"


def test_cached_grounding_read_cannot_falsely_prove_pre_command_values(managed):
    runtime, target, _task = managed
    task = semantic_task(runtime, {"value": 0})
    captures = []
    original = target.observe
    def record():
        value = original()
        captures.append(value)
        return value
    target.observe = record
    frame = runtime.observe(task)
    act(runtime, task, frame)
    assert target.state.fields == (("value", 1),) and len(captures) == 2
    assert captures[1]["fields"] == {"value": 0}
    target.observe = lambda: captures[1]
    with pytest.raises(AgentObservationStale, match="current read"):
        runtime.finish(task)
    assert runtime.get(task).state != "succeeded"


def test_semantic_completion_does_not_coerce_booleans_to_integers(managed):
    runtime, _target, _task = managed
    task = semantic_task(runtime, {"value": True})
    frame = runtime.observe(task)
    act(runtime, task, frame)
    result = runtime.finish(task)
    assert result.state == "waiting_user" and result.verification[0]["status"] == "failed"


def test_unknown_effect_cannot_be_confirmed_by_matching_fields_alone(managed):
    from je_auto_control.utils.agent_runtime.semantic_verification import semantic_matches
    runtime, target, _task = managed
    task = semantic_task(runtime)
    frame = runtime.observe(task)
    target.lose_reply = True
    with pytest.raises(AgentEffectUnknown):
        act(runtime, task, frame)
    with pytest.raises(AgentTaskError, match="waiting_user"):
        runtime.finish(task)
    assert semantic_matches({"kind": "semantic", "tool": "AC_increment", "fields": {"value": 1}},
                            runtime.store.actions(task), target.observe()) is None
    assert runtime.store.actions(task)[0]["status"] == "uncertain"


@pytest.mark.parametrize("clause", [
    {"kind": "semantic", "tool": "AC_unoffered", "fields": {"value": 1}},
    {"kind": "semantic", "tool": "AC_increment", "fields": {}},
    {"kind": "semantic", "tool": "AC_increment", "fields": {"value": []}},
    {"kind": "semantic", "tool": "AC_increment", "fields": {"value": 1}, "address": 4096},
])
def test_semantic_completion_cannot_add_grants_or_unbounded_queries(managed, clause):
    runtime, target, _task = managed
    with pytest.raises(AgentTaskError):
        runtime.submit(AgentTaskSpec(goal="invalid", target="fixture", allowed_tools=("AC_increment",),
                                     success_criteria=(clause,)))
    assert target.calls == [] and target.reads == 0
