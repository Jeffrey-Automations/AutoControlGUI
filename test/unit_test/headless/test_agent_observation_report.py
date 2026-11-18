"""Multi-source reports remain observable while disagreement cannot authorize actions or completion."""
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import sys
import time

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime.errors import AgentObservationStale, AgentTaskError
from je_auto_control.utils.agent_runtime.native_worker import NativeWorker
from je_auto_control.utils.agent_runtime.observation_report import ObservationReport
from je_auto_control.utils.agent_runtime.semantic_native_target import NativeSemanticTarget
from je_auto_control.utils.agent_runtime.semantic_target import fingerprint, observe
from headless.test_agent_semantic_grounding import Target, snapshot, act

FIELDS = ("value",)
SOURCES = ("process_memory", "fixture_protocol")


def report(**changes):
    first = snapshot()
    second = replace(first, source="fixture_protocol", adapter_id="fixture-ipc", **changes)
    return ObservationReport(SOURCES[0], ((SOURCES[0], first), (SOURCES[1], second)), 1, 2, FIELDS)


class ReportTarget(Target):
    observation_sources = SOURCES
    observation_fields = FIELDS

    def __init__(self):
        super().__init__()
        self.second_changes = {}
        self.failure = None

    def observe(self):
        started = time.perf_counter()
        first = snapshot_from(super().observe())
        second = self.failure or replace(first, **({"source": "fixture_protocol", "adapter_id": "fixture-ipc"}
                                                   | self.second_changes))
        return ObservationReport(SOURCES[0], ((SOURCES[0], first), (SOURCES[1], second)),
                                 started, time.perf_counter(), self.observation_fields).to_dict()


def snapshot_from(value):
    from je_auto_control.utils.agent_runtime.semantic_target import SemanticSnapshot
    return SemanticSnapshot.from_dict(value)


@pytest.fixture
def managed(tmp_path):
    target = ReportTarget()
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target})
    spec = AgentTaskSpec(goal="corroborate fixture state", target="fixture", allowed_tools=("AC_increment",),
                         success_criteria=({"kind": "semantic", "tool": "AC_increment", "fields": {"value": 1}},))
    task = runtime.submit(spec).task_id
    try:
        yield runtime, target, task
    finally:
        runtime.close()


def test_complete_report_retains_every_source_in_journal_and_finishes(managed):
    runtime, target, task = managed
    frame = runtime.observe(task)
    assert frame.data["status"] == "complete"
    act(runtime, task, frame)
    grounding = runtime.store.actions(task)[0]["grounding"]
    assert grounding["semantic_sources"] == list(SOURCES)
    assert grounding["semantic_fields"] == list(FIELDS)
    assert set(grounding["semantic_report"]["sources"]) == set(SOURCES)
    assert target.calls[0][1].source == "process_memory"
    assert runtime.finish(task).state == "succeeded"


@pytest.mark.parametrize("change,status", [
    ({"fields": (("value", True),)}, "conflict"),
    ({"revision": 2}, "conflict"),
    ({"revision": None, "consistency": "best_effort"}, "conflict"),
])
def test_disagreement_and_missing_fields_remain_visible_but_cannot_act(managed, change, status):
    runtime, target, task = managed
    target.second_changes = change
    frame = runtime.observe(task)
    assert frame.data["status"] == status
    assert len(frame.data["sources"]) == 2
    with pytest.raises(AgentObservationStale):
        act(runtime, task, frame)
    assert not target.calls and runtime.store.actions(task) == []


@pytest.mark.parametrize("fault", ["failure", "conflict", "revision", "version", "adapter"])
def test_completion_requires_all_current_sources_and_original_provenance(managed, fault):
    runtime, target, task = managed
    act(runtime, task, runtime.observe(task))
    if fault == "failure":
        target.failure = "partial_read"
    else:
        target.second_changes = {"conflict": {"fields": (("value", True),)}, "revision": {"revision": 4},
                                 "version": {"schema_version": "2"}, "adapter": {"adapter_id": "other"}}[fault]
    result = runtime.finish(task)
    assert result.state == "waiting_user"
    assert result.verification == ({"kind": "semantic", "status": "unknown"},)


def test_partial_report_keeps_allowlisted_success_and_fixed_failure(managed):
    runtime, target, task = managed
    target.failure = "partial_read"
    frame = runtime.observe(task)
    assert frame.data["status"] == "partial"
    assert frame.data["sources"]["fixture_protocol"] == {"failure": "partial_read"}
    assert frame.data["sources"]["process_memory"]["snapshot"]["fields"] == {"value": 0}
    with pytest.raises(AgentObservationStale):
        act(runtime, task, frame)


@pytest.mark.parametrize("failure", ["scope_denied", "cleanup_failed", "target_changed", "cancelled", "secret detail"])
def test_control_and_ownership_failures_cannot_be_downgraded_to_missing(failure):
    with pytest.raises(AgentTaskError):
        ObservationReport(SOURCES[0], ((SOURCES[0], snapshot()), (SOURCES[1], failure)), 1, 2, FIELDS)


def test_bool_integer_disagreement_is_not_equal():
    value = report(fields=(("value", False),))
    assert value.status == "conflict" and value.to_dict()["conflicting_fields"] == ["value"]
    with pytest.raises(AgentObservationStale):
        value.require_grounding()


def test_best_effort_agreement_still_cannot_claim_a_checked_generation():
    first = snapshot(revision=None, consistency="best_effort")
    value = ObservationReport(SOURCES[0], ((SOURCES[0], first),
        (SOURCES[1], replace(first, source=SOURCES[1]))), 1, 2, FIELDS)
    assert value.status == "unverified"
    with pytest.raises(AgentObservationStale):
        value.require_grounding()


@pytest.mark.parametrize("change", [{"target_id": "other"}, {"identity_digest": "b" * 64}])
def test_mixed_target_lifetimes_are_refused(change):
    with pytest.raises(AgentObservationStale):
        report(**change)


@pytest.mark.parametrize("change", [{"report_version": True}, {"report_version": 1}, {"report_version": 2}, {"status": "partial"},
                                    {"missing_fields": ["value"]}, {"conflicting_fields": ["value"]},
                                    {"primary": "fixture_protocol"}, {"extra": "ignored"}])
def test_unknown_or_forged_report_schema_is_refused(change):
    with pytest.raises(AgentTaskError):
        ObservationReport.from_dict(report().to_dict() | change, required=SOURCES, fields=FIELDS)


def test_host_contract_cannot_be_widened_by_a_report():
    with pytest.raises(AgentTaskError, match="host source contract"):
        ObservationReport.from_dict(report().to_dict(), required=(SOURCES[0],), fields=FIELDS)
    target = Target()
    target.observe = lambda: report().to_dict()
    with pytest.raises(AgentTaskError, match="unknown schema"):
        observe(target)


def test_stale_capture_envelope_and_cached_sources_are_refused():
    with pytest.raises(AgentTaskError, match="capture envelope"):
        replace(report(), started=1.5)
    target = ReportTarget()
    target.observe = lambda: report().to_dict()
    with pytest.raises(AgentObservationStale, match="current read"):
        observe(target)


@pytest.mark.parametrize("stamp", [10**400, -1, True, float("inf"), float("nan")])
def test_invalid_report_times_fail_with_framework_error(stamp):
    with pytest.raises(AgentTaskError):
        replace(report(), finished=stamp)


def test_source_versions_affect_grounding_but_capture_metadata_does_not():
    target = ReportTarget()
    original = report()
    newer = replace(original, sources=tuple((name, replace(value, observation_id="next", started=2, finished=3))
                                            for name, value in original.sources), started=2, finished=3)
    assert fingerprint(target, original.to_dict()) == fingerprint(target, newer.to_dict())
    assert fingerprint(target, original.to_dict()) != fingerprint(target, report(schema_version="2").to_dict())


def test_worker_roundtrip_and_proxy_require_explicit_host_report_contract(tmp_path):
    target = ReportTarget()
    source = BytesIO(json.dumps({"id": "1", "operation": "bootstrap", "payload": {}}).encode() + b"\n")
    sink = BytesIO()
    worker = NativeWorker(source, sink, target=target)
    worker.run()
    bootstrap = json.loads(sink.getvalue())["result"]
    proxy = NativeSemanticTarget(argv=["unused"], resource_path=tmp_path / "unused.lock")
    assert not proxy._supports_bootstrap(bootstrap)

    class ReportProxy(NativeSemanticTarget):
        observation_sources = SOURCES
        observation_fields = FIELDS

    report_proxy = ReportProxy(argv=["unused"], resource_path=tmp_path / "unused.lock")
    assert report_proxy._supports_bootstrap(bootstrap)
    for change in ({"semantic_report": True}, {"semantic_report": 1}, {"semantic_report": 2}, {"semantic_sources": [SOURCES[0]]},
                   {"semantic_fields": []}, {"semantic_fields": ["other"]}):
        assert not report_proxy._supports_bootstrap(bootstrap | change)
    value = observe(target)
    assert ObservationReport.from_dict(
        json.loads(json.dumps(value)), required=SOURCES, fields=FIELDS).status == "complete"


@pytest.mark.parametrize("partial", [False, True])
def test_hidden_helper_preserves_report_through_actual_runtime_protocol(tmp_path, partial):
    class ReportProxy(NativeSemanticTarget):
        observation_sources = SOURCES
        observation_fields = FIELDS

    helper = Path(__file__).resolve().parents[2] / "fixtures" / "reported_semantic_helper.py"
    argv = [sys.executable, "-u", str(helper)] + (["--partial"] if partial else [])
    target = ReportProxy(argv=argv, resource_path=tmp_path / "report.lock")
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target})
    spec = AgentTaskSpec(goal="corroborate helper", target="fixture", allowed_tools=("AC_increment",),
                         success_criteria=({"kind": "semantic", "tool": "AC_increment", "fields": {"value": 1}},))
    try:
        task = runtime.submit(spec).task_id
        frame = runtime.observe(task)
        channel = target._channel
        assert frame.data["status"] == ("partial" if partial else "complete")
        if partial:
            with pytest.raises(AgentObservationStale):
                act(runtime, task, frame)
            assert not runtime.store.actions(task)
        else:
            act(runtime, task, frame)
            assert runtime.finish(task).state == "succeeded"
    finally:
        runtime.close()
    assert channel.retired


def test_all_sources_omitting_required_field_cannot_authorize():
    first = snapshot(fields=(("other", 0),))
    value = ObservationReport(SOURCES[0], ((SOURCES[0], first),
        (SOURCES[1], replace(first, source=SOURCES[1]))), 1, 2, ("other", "value"))
    assert value.status == "partial"
    assert value.to_dict()["missing_fields"] == ["value"]
    with pytest.raises(AgentObservationStale):
        value.require_grounding()


@pytest.mark.parametrize("fields", [(), ("value", "value"), ("",), tuple(f"field{i}" for i in range(65))])
def test_invalid_host_field_contract_is_refused(fields):
    with pytest.raises(AgentTaskError):
        replace(report(), field_scope=fields)


def test_all_failed_sources_report_entire_missing_scope():
    value = ObservationReport(SOURCES[0], tuple((name, "partial_read") for name in SOURCES),
                              1, 2, ("other", "value"))
    assert value.status == "partial"
    assert value.to_dict()["missing_fields"] == ["other", "value"]


def test_source_cannot_publish_unrequested_fields():
    with pytest.raises(AgentTaskError, match="host field contract"):
        report(fields=(("other", 0),))


@pytest.mark.parametrize("fields", [("other",), ("value", "other"), ()])
def test_report_cannot_change_host_field_scope(fields):
    with pytest.raises(AgentTaskError):
        ObservationReport.from_dict(report().to_dict(), required=SOURCES, fields=fields)


def test_shared_omission_blocks_runtime_action(managed):
    runtime, target, task = managed
    target.observation_fields = ("other", "value")
    frame = runtime.observe(task)
    assert frame.data["missing_fields"] == ("other",)
    with pytest.raises(AgentObservationStale):
        act(runtime, task, frame)
    assert not target.calls and runtime.store.actions(task) == []


def test_shared_omission_after_action_cannot_prove_completion(managed):
    runtime, target, task = managed
    target.observation_fields = ("other", "value")
    target.state = replace(target.state, fields=(("other", 0), ("value", 0)))
    act(runtime, task, runtime.observe(task))
    assert target.calls and dict(target.state.fields) == {"value": 1}
    result = runtime.finish(task)
    assert result.state == "waiting_user"
    assert result.verification == ({"kind": "semantic", "status": "unknown"},)


def test_completion_preserves_original_field_scope_if_target_changes(managed):
    runtime, target, task = managed
    target.observation_fields = ("other", "value")
    target.state = replace(target.state, fields=(("other", 0), ("value", 0)))
    act(runtime, task, runtime.observe(task))
    target.observation_fields = FIELDS
    result = runtime.finish(task)
    assert result.state == "waiting_user"
    assert result.verification[0]["status"] == "unknown"
    assert result.verification[0]["reason"] == "AgentTaskError"
