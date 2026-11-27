"""DOM fields normalize into the shared observation report with source identity. No Qt, no browser."""
import pytest

from je_auto_control.utils.agent_runtime.browser_target import BrowserTarget
from je_auto_control.utils.agent_runtime.dom_observation import DomField, DomSource, dom_fields, stable_state
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.observation_report import ObservationReport
from je_auto_control.utils.agent_runtime.target_config import AgentTargetProfile

FIELDS = [{"name": "document_id", "selector": "#doc", "property": "value"},
          {"name": "job_status", "selector": "#status", "frame": "#panel", "property": "text"},
          {"name": "banner", "selector": ".banner", "property": "visible"}]


class SdkError(Exception):
    """Stands in for je_web_runner's ManagedBrowserError, which carries a fixed reason."""

    def __init__(self, reason):
        super().__init__("managed browser: " + reason)
        self.reason = reason


class Session:
    def __init__(self):
        self.context_id = "ctx-1"
        self.urls = ["https://app.example/a"]
        self.present = {"#doc": True, "#status": True, ".banner": False}
        self.values = {"#doc": "D-7", "#status": "done"}
        self.refuse = set()
        self.fault = None
        self.calls = []

    @property
    def url(self):
        return self.urls.pop(0) if len(self.urls) > 1 else self.urls[0]

    def visible(self, selector, frame=""):
        if "[data-secret]" in selector:
            return False  # this page marks nothing
        self.calls.append(("visible", selector, frame))
        if self.fault:
            raise SdkError(self.fault)
        return self.present[selector]

    def _read(self, selector, frame, reason):
        self.calls.append(("read", selector, frame))
        if selector in self.refuse:
            raise SdkError(reason)
        return self.values[selector]

    def text(self, selector, frame=""):
        return self._read(selector, frame, "text_readback_refused")

    def read_value(self, selector, frame=""):
        return self._read(selector, frame, "value_readback_refused")


def source():
    return DomSource("shop", dom_fields(FIELDS))


def report(session):
    return source().report(session, lambda: None)


def test_all_present_fields_make_a_complete_best_effort_snapshot():
    value = report(Session()).to_dict()
    snapshot = value["sources"]["dom"]["snapshot"]
    assert snapshot["fields"] == {"banner": False, "document_id": "D-7", "job_status": "done"}
    assert (snapshot["source"], snapshot["adapter_id"], snapshot["consistency"], snapshot["revision"]) == (
        "dom", "webrunner_dom", "best_effort", None)
    assert snapshot["target_id"] == "shop"
    # The DOM has no revision counter, so the report never claims checked consistency.
    assert value["status"] == "unverified"


def test_identity_follows_the_browser_context_not_the_url():
    first, second = Session(), Session()
    second.urls = ["https://app.example/other"]
    third = Session()
    third.context_id = "ctx-2"
    digests = [report(item).to_dict()["sources"]["dom"]["snapshot"]["identity_digest"]
               for item in (first, second, third)]
    assert digests[0] == digests[1] != digests[2]


def test_absent_and_refused_fields_are_reported_per_field():
    session = Session()
    session.present["#doc"] = False
    session.refuse.add("#status")
    value = report(session).to_dict()
    partial = value["sources"]["dom"]["partial"]
    assert partial["failures"] == {"document_id": "not_found", "job_status": "protected"}
    assert partial["fields"] == {"banner": False}
    assert value["status"] == "partial" and value["missing_fields"] == ["document_id", "job_status"]
    # A missing element is probed with visible() and never read, which would fault the SDK session.
    assert ("read", "#doc", "") not in session.calls


def test_a_navigation_during_capture_makes_the_source_inconsistent():
    session = Session()
    session.urls = ["https://app.example/a", "https://app.example/b"]
    value = report(session).to_dict()
    assert value["sources"]["dom"] == {"failure": "inconsistent_snapshot"}
    assert value["status"] == "partial"


@pytest.mark.parametrize("fault", ["operation_failed", "retired", "wrong_thread"])
def test_sticky_sdk_faults_raise_instead_of_passing_as_one_field(fault):
    session = Session()
    session.fault = fault
    with pytest.raises(AgentTaskError, match="semantic read failed"):
        report(session)


def test_a_missing_browser_context_identity_is_refused():
    session = Session()
    session.context_id = None
    with pytest.raises(AgentTaskError, match="context identity"):
        report(session)


def test_checkpoints_bracket_every_sdk_call():
    session, seen = Session(), []
    source().capture(session, lambda: seen.append(len(session.calls)))
    # Two checks per SDK call (URL reads included), so a revocation is seen between any two calls.
    assert len(seen) == 2 * (len(session.calls) + 2)


def test_a_revocation_checkpoint_stops_the_capture():
    session = Session()

    def revoked():
        if session.calls:
            raise AgentTaskError("revoked")

    with pytest.raises(AgentTaskError, match="revoked"):
        source().capture(session, revoked)
    assert len(session.calls) == 1


def test_the_report_round_trips_through_the_closed_wire_schema():
    value = report(Session()).to_dict()
    again = ObservationReport.from_dict(value, required=("dom",), fields=("banner", "document_id", "job_status"))
    assert again.to_dict() == value


def test_stable_state_drops_only_capture_ids_and_times():
    first, second = stable_state(report(Session())), stable_state(report(Session()))
    assert first == second
    assert "started" not in first and "observation_id" not in first["sources"]["dom"]["snapshot"]
    changed = Session()
    changed.values["#status"] = "running"
    assert stable_state(report(changed)) != first
    partial = Session()
    partial.present["#doc"] = False
    assert "observation_id" not in stable_state(report(partial))["sources"]["dom"]["partial"]["capture"]


@pytest.mark.parametrize("value", [[], [{"name": "a", "selector": "", "property": "text"}],
                                   [{"name": "a", "selector": "#a", "property": "html"}],
                                   [{"name": "a b", "selector": "#a", "property": "text"}],
                                   [{"name": "a", "selector": "#a", "property": "text", "script": "x"}],
                                   [{"name": "a", "selector": "#a", "property": "text"}] * 2,
                                   [{"name": f"f{i}", "selector": "#a", "property": "text"} for i in range(65)],
                                   "not a list"])
def test_unreviewed_field_settings_are_refused(value):
    with pytest.raises(AgentTaskError):
        dom_fields(value)


def test_browser_profiles_accept_and_normalize_semantic_fields():
    profile = AgentTargetProfile.from_dict({
        "name": "shop", "kind": "browser", "allowed_tools": ["AC_browser_read"],
        "settings": {"allowed_origins": ["https://app.example"], "semantic_fields": FIELDS}})
    names = [item["name"] for item in profile.to_dict()["settings"]["semantic_fields"]]
    assert names == ["banner", "document_id", "job_status"]
    assert profile.to_dict()["settings"]["semantic_fields"][1]["frame"] == ""
    with pytest.raises(AgentTaskError):
        AgentTargetProfile.from_dict({
            "name": "files", "kind": "files", "allowed_tools": [], "roots": [],
            "settings": {"semantic_fields": FIELDS}})


def test_browser_target_adds_the_stable_report_only_when_configured():
    plain, configured = BrowserTarget(), BrowserTarget(target_id="shop", semantic_fields=FIELDS)
    for target in (plain, configured):
        target._session = type("Raw", (Session,), {"observe": lambda self: {"url": "https://app.example/a"}})()
    assert "semantic_report" not in plain.observe()
    observed = configured.observe()
    assert observed["semantic_report"]["sources"]["dom"]["snapshot"]["fields"]["job_status"] == "done"
    assert observed["semantic_report"] == configured.observe()["semantic_report"]


def test_field_objects_validate_directly():
    with pytest.raises(AgentTaskError):
        DomField("a", "#a\0", "", "text")
    assert DomField("a", "#a", "", "visible").to_dict() == {
        "name": "a", "selector": "#a", "frame": "", "property": "visible"}
