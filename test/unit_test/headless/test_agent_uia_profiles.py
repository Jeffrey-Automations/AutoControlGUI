"""Use a zero-action UI profile through pinned deployment and owned helper boundaries."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime import native_target, target_config, uia_deployment
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.target_config import AgentTargetProfile
from je_auto_control.utils.rbac.authorization import AuthorizationContext, authorization_scope

IMAGE_BYTES = b"measured image bytes"


def config(tmp_path, **changes):
    data = {"schema": 1, "kind": "uia_fixture", "host": "owned-host", "target": "fixture",
            "image": "C:\\owned\\python.exe", "image_sha256": hashlib.sha256(IMAGE_BYTES).hexdigest(),
            "max_image_bytes": 64 << 20, "attestation_timeout": 5} | changes
    path = tmp_path / "ui-deployment.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return {"name": "fixture", "kind": "uia_fixture", "allowed_tools": [], "roots": [], "apps": [],
            "settings": {"config_path": str(path), "config_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}


def task(**changes):
    return {"goal": "inspect owned window", "target": "fixture", "allowed_tools": [],
            "success_criteria": [{"kind": "actions_complete"}], "budget": {"action_seconds": 3}, **changes}


@pytest.fixture(autouse=True)
def windows_host(monkeypatch):
    monkeypatch.setattr(target_config, "sys", SimpleNamespace(platform="win32", maxsize=2**63-1))


def test_empty_tool_scope_is_external_and_has_no_planned_actions():
    definition = AgentTaskSpec.from_dict(task())
    assert definition.allowed_tools == ()
    for change in ({"mode": "ollama"}, {"mode": "skill"}, {"actions": [{"tool": "AC_write"}]},
                   {"actions": {}}, {"success_criteria": []}):
        with pytest.raises(AgentTaskError):
            AgentTaskSpec.from_dict(task(**change))


def test_zero_action_scope_rejects_every_command_and_empty_plan_does_not_finish(tmp_path):
    from headless.test_agent_runtime import FakeTarget
    target = FakeTarget()
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target})
    try:
        handle = runtime.submit(task()).task_id
        frame = runtime.observe(handle)
        with pytest.raises(AgentTaskError):
            runtime.act(handle, {"tool": "AC_increment", "observation_id": frame.observation_id})
        assert runtime.finish(handle).state == "waiting_user"
        assert target.calls == [] and runtime.store.actions(handle) == []
    finally:
        runtime.close()


def test_static_uia_deployment_has_separate_identity_and_fresh_session(tmp_path, monkeypatch):
    value = config(tmp_path)["settings"]
    reads = []
    def read(path, limit):
        reads.append((str(path), limit))
        return IMAGE_BYTES
    monkeypatch.setattr(uia_deployment, "read_artifact", read)
    first = uia_deployment.load_uia_image(value["config_path"], value["config_sha256"])
    second = uia_deployment.load_uia_image(value["config_path"], value["config_sha256"])
    assert first.pin.session != second.pin.session
    assert (first.pin.executable, first.pin.version) == ("uia-fixture", "1")
    assert reads == [(str(Path("C:\\owned\\python.exe")), 64 << 20)] * 2
    with pytest.raises(AgentTaskError):
        uia_deployment.load_uia_image(value["config_path"], "0" * 64)
    assert len(reads) == 2


@pytest.mark.parametrize("change", [
    {"schema": True}, {"schema": 2}, {"kind": "fixture"}, {"pid": 42}, {"argv": []},
    {"session": "reused"}, {"image": "relative.exe"}, {"image_sha256": "0" * 64},
    {"attestation_timeout": True}, {"max_image_bytes": 0}, {"target": "../bad"},
])
def test_invalid_ui_deployment_is_refused_before_native_construction(tmp_path, monkeypatch, change):
    value = config(tmp_path, **change)["settings"]
    monkeypatch.setattr(uia_deployment, "read_artifact", lambda *_: IMAGE_BYTES)
    with pytest.raises(AgentTaskError, match="^UI fixture deployment is invalid$"):
        uia_deployment.load_uia_image(value["config_path"], value["config_sha256"])


@pytest.mark.parametrize("change", [{"allowed_tools": ["AC_write"]}, {"roots": ["C:/"]},
                                    {"apps": ["anything"]}, {"settings": {"argv": ["unreviewed"]}}])
def test_ui_profile_cannot_grant_actions_or_other_resources(tmp_path, change):
    with pytest.raises(AgentTaskError):
        AgentTargetProfile.from_dict(config(tmp_path) | change)


def test_registration_reload_probe_and_host_configuration_remain_inert(tmp_path, monkeypatch):
    monkeypatch.setattr(native_target, "owned_channel", lambda *_a, **_k: pytest.fail("helper launched"))
    value = config(tmp_path)
    database = tmp_path / "runtime.sqlite"
    runtime = AgentRuntime(database)
    try:
        with authorization_scope(AuthorizationContext("operator", "operator")), pytest.raises(AgentTaskError):
            runtime.target_profiles.control("register", value)
        summary = runtime.target_profiles.control("register", value)
        assert summary["kind"] == "uia_fixture" and summary["declared_tools"] == []
        runtime.target_profiles.control("probe", {"name": "fixture"})
        for key in ("config_path", "config_sha256"):
            with pytest.raises(AgentTaskError, match="host configuration"):
                runtime.submit(task(options={key: "other"}))
        runtime.target_profiles.control("disable", {"name": "fixture"})
        with pytest.raises(AgentTaskError, match="disabled"):
            runtime.submit(task())
    finally:
        runtime.close()
    restored = AgentRuntime(database)
    try:
        adapter = restored._targets["fixture"]
        assert adapter._channel is None
        assert adapter._argv[1:5] == ("-I", "-u", "-m", "je_auto_control.utils.agent_runtime.uia_worker")
        assert adapter.probe() == {"status": "not_supported", "native_evidence": "not_recorded"}
        assert restored.target_profiles.control("get", {"name": "fixture"})["profile"] == value
    finally:
        restored.close()


def test_real_hidden_worker_preserves_readonly_profile_and_cleans_up(tmp_path):
    runtime = AgentRuntime(tmp_path / "runtime.sqlite")
    try:
        runtime.target_profiles.control("register", config(tmp_path))
        adapter = runtime._targets["fixture"]
        helper = Path(__file__).resolve().parents[2] / "fixtures" / "uia_worker_helper.py"
        reference = adapter._profile.settings
        adapter._argv = (sys.executable, "-u", str(helper), reference["config_path"], reference["config_sha256"])
        handle = runtime.submit(task()).task_id
        frame = runtime.observe(handle)
        assert frame.data["status"] == "partial"
        values = frame.data["sources"]["uia"]["partial"]["fields"]
        assert values["empty"] == "" and values["enabled"] is False
        channel = adapter._channel
        with pytest.raises(AgentTaskError):
            runtime.act(handle, {"tool": "AC_fixture_set_state", "observation_id": frame.observation_id})
        runtime.target_profiles.control("disable", {"name": "fixture"})
        assert channel.retired and runtime.store.actions(handle) == []
    finally:
        runtime.close()
