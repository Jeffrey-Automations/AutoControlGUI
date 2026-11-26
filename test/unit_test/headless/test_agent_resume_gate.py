"""A first action waits for a fresh observation that passes every resume condition."""
import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskError, AgentTaskSpec
from je_auto_control.utils.agent_runtime.errors import AgentHumanReview
from je_auto_control.utils.agent_runtime.resume_gate import RESUME_KINDS, validate_resume_conditions
from je_auto_control.utils.agent_runtime.store import request_spec_digest

SIGNED_IN = {"kind": "screen", "spec": {"text_present": "Signed in"}}


class Session:
    """A fixture application whose visible text says whether the session survived."""

    def __init__(self):
        self.text, self.value, self.calls = "Sign in", 0, []

    def observe(self):
        return {"identity": "fixture", "elements": [{"name": self.text}, {"name": str(self.value)}],
                "geometry": [0, 0, 100, 100]}

    def ready(self, _spec):
        return True, ""

    def perform(self, name, arguments):
        self.calls.append(name)
        self.value += 1
        return {"value": self.value}

    def cleanup(self):
        return None


def spec(**changes):
    values = {"goal": "continue the signed-in work", "target": "fixture", "allowed_tools": ["AC_increment"],
              "success_criteria": [{"kind": "result_equals", "key": "value", "value": 2}]}
    values.update(changes)
    return AgentTaskSpec.from_dict(values)


@pytest.fixture
def managed(tmp_path):
    target = Session()
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target})
    yield runtime, target
    runtime.close()


def act(runtime, task_id):
    frame = runtime.observe(task_id)
    return runtime.act(task_id, {"tool": "AC_increment", "arguments": {}, "observation_id": frame.observation_id})


def test_an_empty_field_leaves_every_existing_spec_and_digest_unchanged():
    plain = spec()
    assert "resume_conditions" not in plain.to_dict()
    assert AgentTaskSpec.from_dict(plain.to_dict()) == plain
    declared = spec(resume_conditions=[SIGNED_IN])
    assert declared.to_dict()["resume_conditions"] == [SIGNED_IN]
    assert request_spec_digest(declared.to_dict()) != request_spec_digest(plain.to_dict())


@pytest.mark.parametrize("clause", [
    {"kind": "result_equals", "key": "value", "value": 1},
    {"kind": "actions_complete"},
    {"kind": "unknown"},
])
def test_history_and_unknown_clauses_cannot_prove_current_state(clause):
    with pytest.raises(AgentTaskError):
        validate_resume_conditions([clause])


def test_only_fresh_state_kinds_are_allowed_and_the_count_is_bounded():
    assert RESUME_KINDS == {"screen", "browser", "file_exists", "file_sha256", "file_text", "file_manifest"}
    with pytest.raises(AgentTaskError, match="at most 32"):
        validate_resume_conditions([SIGNED_IN] * 33)


def test_submission_rejects_an_invalid_resume_condition(managed):
    runtime, _target = managed
    unknown = spec(resume_conditions=[{"kind": "actions_complete"}])
    incomplete = spec(resume_conditions=[{"kind": "screen"}])
    with pytest.raises(AgentTaskError):
        runtime.submit(unknown)
    with pytest.raises(AgentTaskError):
        runtime.submit(incomplete)


def test_the_first_action_waits_while_the_state_is_not_re_established(managed):
    runtime, target = managed
    task = runtime.submit(spec(resume_conditions=[SIGNED_IN]))
    with pytest.raises(AgentHumanReview, match="resume state is not re-established"):
        act(runtime, task.task_id)
    assert target.calls == []
    current = runtime.get(task.task_id)
    assert current.state == "waiting_user"
    assert current.verification == ({"kind": "screen", "status": "failed"},)
    assert "resume state is not re-established" in current.reason


def test_a_passing_fresh_observation_admits_the_first_action_and_then_the_gate_is_spent(managed):
    runtime, target = managed
    target.text = "Signed in"
    task = runtime.submit(spec(resume_conditions=[SIGNED_IN]))
    assert act(runtime, task.task_id).result == {"value": 1}
    target.text = "Sign in"
    assert act(runtime, task.task_id).result == {"value": 2}
    assert target.calls == ["AC_increment", "AC_increment"]


def test_an_older_passing_observation_does_not_admit_an_action_on_a_newer_failing_one(managed):
    runtime, target = managed
    target.text = "Signed in"
    task = runtime.submit(spec(resume_conditions=[SIGNED_IN]))
    runtime.observe(task.task_id)
    target.text = "Sign in"
    with pytest.raises(AgentHumanReview):
        act(runtime, task.task_id)
    assert target.calls == []


def test_a_task_without_resume_conditions_is_unaffected(managed):
    runtime, target = managed
    task = runtime.submit(spec())
    assert act(runtime, task.task_id).result == {"value": 1}


def test_a_recovery_reviewer_may_add_resume_conditions_but_not_change_the_source_scope():
    from je_auto_control.utils.agent_runtime.task_recovery import _check_scope
    template = {key: value for key, value in spec().to_dict().items()}
    _check_scope(template, {**template, "resume_conditions": [SIGNED_IN]})
    with pytest.raises(AgentTaskError, match="preserve source scope"):
        _check_scope(template, {**template, "success_criteria": [{"kind": "actions_complete"}]})


def test_a_recovery_reviewer_may_not_drop_or_weaken_the_source_resume_conditions():
    from je_auto_control.utils.agent_runtime.task_recovery import _check_scope
    window = {"kind": "screen", "spec": {"text_present": "Order 42"}}
    template = spec(resume_conditions=[SIGNED_IN, window]).to_dict()
    _check_scope(template, {**template, "resume_conditions": [window, SIGNED_IN]})  # order is not strength
    _check_scope(template, {**template, "resume_conditions": [SIGNED_IN, window, {"kind": "file_exists",
                                                                                  "path": "draft.txt"}]})
    without = {key: value for key, value in template.items() if key != "resume_conditions"}
    weakened = {"kind": "screen", "spec": {"text_present": "Signed"}}
    for reviewed in (without, {**template, "resume_conditions": []}, {**template, "resume_conditions": [window]},
                     {**template, "resume_conditions": [weakened, window]}):
        with pytest.raises(AgentTaskError, match="keep every source resume condition"):
            _check_scope(template, reviewed)


def test_browser_helper_reads_a_declared_resume_condition(monkeypatch):
    from je_auto_control.utils.agent_runtime import browser_verification
    from je_auto_control.utils.agent_runtime.browser_target import BrowserTarget
    clause = {"kind": "browser", "operation": "visible", "selector": "#account", "value": True}
    target = BrowserTarget()
    target._session = object()
    target._spec = spec(resume_conditions=[clause])
    monkeypatch.setattr(browser_verification, "evaluate_browser_clause", lambda *_args: True)
    assert target.verify_browser(dict(clause)) is True
    with pytest.raises(AgentTaskError, match="outside the owned task"):
        target.verify_browser({**clause, "selector": "#other"})
