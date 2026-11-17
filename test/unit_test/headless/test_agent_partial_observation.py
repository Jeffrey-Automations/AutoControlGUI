"""Partial source values remain diagnostic through report parsing and action gates."""
from dataclasses import replace

import pytest

from je_auto_control.utils.agent_runtime.errors import AgentObservationStale, AgentTaskError
from je_auto_control.utils.agent_runtime.observation_report import ObservationReport
from je_auto_control.utils.agent_runtime.partial_observation import PartialObservation
from headless.test_agent_semantic_grounding import snapshot


def partial(**changes):
    value = PartialObservation(snapshot().capture, (("empty", ""), ("enabled", False)),
                               (("value", "protected"),))
    return replace(value, **changes)


def test_partial_roundtrip_keeps_empty_false_and_failure_distinct():
    value = partial()
    assert PartialObservation.from_dict(value.to_dict()) == value
    report = ObservationReport("process_memory", (("process_memory", value),), 1, 2,
                               ("empty", "enabled", "value"))
    wire = report.to_dict()
    assert wire["status"] == "partial" and wire["missing_fields"] == ["value"]
    assert wire["sources"]["process_memory"]["partial"]["fields"] == {"empty": "", "enabled": False}
    assert ObservationReport.from_dict(wire, required=("process_memory",),
        fields=("empty", "enabled", "value")) == report
    with pytest.raises(AgentObservationStale):
        report.require_grounding()
    with pytest.raises(AgentObservationStale):
        report.grounding()


@pytest.mark.parametrize("change", [
    {"failures": ()}, {"failures": (("empty", "protected"),)},
    {"fields": (("enabled", False), ("enabled", False))},
    {"failures": (("value", "protected"), ("value", "protected"))},
    {"failures": (("value", "scope_denied"),)}, {"failures": (("value", "secret detail"),)},
    {"capture": {}},
])
def test_invalid_partial_contract_cannot_enter_report(change):
    with pytest.raises(AgentTaskError):
        partial(**change)


def test_partial_must_account_for_entire_host_scope():
    with pytest.raises(AgentTaskError, match="host field contract"):
        ObservationReport("process_memory", (("process_memory", partial()),), 1, 2,
                          ("empty", "enabled", "value", "missing"))


def test_known_partial_conflicts_are_not_discarded():
    first = snapshot(fields=(("empty", ""), ("enabled", 0), ("value", "public")))
    second = replace(partial(), capture=replace(first.capture, source="uia"))
    report = ObservationReport("process_memory", (("process_memory", first), ("uia", second)),
                               1, 2, ("empty", "enabled", "value"))
    assert report.status == "conflict"
    assert report.to_dict()["conflicting_fields"] == ["enabled"]
    assert report.to_dict()["missing_fields"] == ["value"]


def test_failed_all_fields_requires_no_dummy_value():
    value = PartialObservation(snapshot().capture, (), (("value", "unsupported"),))
    report = ObservationReport("process_memory", (("process_memory", value),), 1, 2, ("value",))
    assert report.status == "partial" and dict(value.fields) == {}


@pytest.mark.parametrize("change", [{"identity_digest": "other"}, {"target_id": "other"}])
def test_partial_source_cannot_mix_target_lifetimes(change):
    first = snapshot(fields=(("empty", ""), ("enabled", False), ("value", 0)))
    value = partial(capture=replace(first.capture, source="uia", **change))
    with pytest.raises(AgentObservationStale):
        ObservationReport("process_memory", (("process_memory", first), ("uia", value)),
                          1, 2, ("empty", "enabled", "value"))


@pytest.mark.parametrize("change", [{"revision": True}, {"finished": 10**400}, {"extra": 1}])
def test_partial_metadata_uses_complete_snapshot_validation(change):
    wire = partial().to_dict()
    wire["capture"].update(change)
    with pytest.raises(AgentTaskError):
        PartialObservation.from_dict(wire)


def test_partial_is_never_accepted_as_complete_snapshot():
    from je_auto_control.utils.agent_runtime.semantic_snapshot import SemanticSnapshot
    with pytest.raises(AgentTaskError):
        SemanticSnapshot.from_dict(partial().to_dict())
