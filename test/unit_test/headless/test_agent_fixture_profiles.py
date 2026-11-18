"""Manage fixture profiles and both deployment bindings without native execution."""
from dataclasses import replace
from pathlib import PureWindowsPath
from io import BytesIO
from types import SimpleNamespace

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime
from je_auto_control.utils.agent_runtime import native_target, target_config
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.fixture_commands import FIXTURE_COMMAND
from je_auto_control.utils.agent_runtime.fixture_observations import FIXTURE_FIELDS, FIXTURE_SOURCES
from je_auto_control.utils.agent_runtime.fixture_deployment import load_fixture_image
from je_auto_control.utils.agent_runtime.fixture_native_target import NativeFixtureTarget
from je_auto_control.utils.agent_runtime.fixture_worker import FixtureWorker
from je_auto_control.utils.agent_runtime.pinned_deployment import is_local_absolute
from je_auto_control.utils.agent_runtime.target_config import AgentTargetProfile
from je_auto_control.utils.rbac.authorization import AuthorizationContext, authorization_scope
from headless.test_agent_fixture_readiness import spec
from headless.test_agent_fixture_worker import deployment, injected, profile_request


@pytest.fixture(autouse=True)
def windows_profile_host(monkeypatch):
    monkeypatch.setattr(target_config, "sys", SimpleNamespace(platform="win32", maxsize=2**63-1))


def config(tmp_path):
    path, digest = deployment(tmp_path)
    return profile_request(path, digest)["profile"]


@pytest.mark.parametrize("change", [
    {"allowed_tools": ["AC_write"]}, {"roots": ["C:/"]}, {"apps": ["anything"]},
    {"settings": {"config_path": "relative", "config_sha256": "0" * 64}},
    {"settings": {"config_path": "C:/fixed", "config_sha256": True}},
    {"settings": {"config_path": '\\\\host\\share\\c.json', "config_sha256": "0" * 64}},
    {"settings": {"config_path": "//host/share/c.json", "config_sha256": "0" * 64}},
    {"settings": {"config_path": '\\\\.\\pipe\\fixture', "config_sha256": "0" * 64}},
    {"settings": {"argv": ["anything"]}},
])
def test_profile_refuses_other_capabilities_and_launch_settings(tmp_path, change):
    with pytest.raises(AgentTaskError):
        AgentTargetProfile.from_dict(config(tmp_path) | change)


def test_registration_and_reload_are_inert_and_require_host_management(tmp_path, monkeypatch):
    monkeypatch.setattr(native_target, "owned_channel", lambda *_a, **_k: pytest.fail("helper launched"))
    database = tmp_path / "runtime.sqlite"
    value = config(tmp_path)
    runtime = AgentRuntime(database)
    try:
        with authorization_scope(AuthorizationContext("operator", "operator")), pytest.raises(AgentTaskError):
            runtime.target_profiles.control("register", value)
        result = runtime.target_profiles.control("register", value)
        assert result["kind"] == "fixture" and result["native_evidence"] == "not_recorded"
        assert result["declared_tools"] == [FIXTURE_COMMAND]
        for key in ("config_path", "config_sha256"):
            with pytest.raises(AgentTaskError, match="host configuration"):
                runtime.submit(replace(spec(), options={key: "other"}))
    finally:
        runtime.close()
    restored = AgentRuntime(database)
    try:
        details = restored.target_profiles.control("get", {"name": "fixture"})
        assert details["profile"] == value
        assert restored._targets["fixture"]._channel is None
        argv = restored._targets["fixture"]._argv
        assert argv[1:5] == ("-I", "-u", "-m", "je_auto_control.utils.agent_runtime.fixture_worker")
    finally:
        restored.close()


@pytest.mark.parametrize("change", [{"version": True}, {"version": 1.0}, {"version": 2},
                                    {"config_sha256": "0" * 64}, {"target": "other"}, {"extra": 1}])
def test_proxy_requires_exact_loaded_deployment_bootstrap(tmp_path, change):
    value = config(tmp_path)
    target = NativeFixtureTarget(AgentTargetProfile.from_dict(value))
    contract = {"version": 1, "config_sha256": value["settings"]["config_sha256"], "target": "fixture"}
    bootstrap = {"protocol": 1, "semantic": 1, "semantic_report": 3,
                 "semantic_sources": list(FIXTURE_SOURCES), "semantic_fields": list(FIXTURE_FIELDS)}
    assert target._supports_bootstrap(bootstrap | {"fixture": contract})
    assert not target._supports_bootstrap(bootstrap | {"fixture": contract | change})


def test_wrong_bootstrap_is_retired_before_any_configure(tmp_path, monkeypatch):
    target = NativeFixtureTarget(AgentTargetProfile.from_dict(config(tmp_path)))
    requests = []

    class Channel:
        retired = False

        def request(self, operation, _payload, **_kwargs):
            requests.append(operation)
            return {"protocol": 1, "semantic": 1, "semantic_report": 3,
                    "semantic_sources": list(FIXTURE_SOURCES), "semantic_fields": list(FIXTURE_FIELDS), "fixture": {
                "version": 1, "config_sha256": "0" * 64, "target": "fixture"}}

        def close(self):
            self.retired = True

    channel = Channel()
    monkeypatch.setattr(native_target, "owned_channel", lambda *_a, **_k: channel)
    with pytest.raises(AgentTaskError, match="bootstrap"):
        target._launch(lambda: None)
    assert channel.retired and requests == ["bootstrap"]
    target.cleanup()


@pytest.mark.parametrize("change", ["absent", "path", "digest", "target", "pin"])
def test_worker_rejects_different_profile_before_mutation_or_acquisition(tmp_path, change):
    path, digest = deployment(tmp_path)
    image = load_fixture_image(str(path), digest)
    target, _, calls, *_ = injected(image)
    worker = FixtureWorker(BytesIO(), BytesIO(), target=target,
                           reference={"config_path": str(path), "config_sha256": digest}, target_id="fixture")
    payload = profile_request(path, digest)
    if change == "absent":
        payload.pop("profile")
    elif change == "path":
        payload["profile"]["settings"]["config_path"] = str(tmp_path / "another.json")
    elif change == "digest":
        payload["profile"]["settings"]["config_sha256"] = "0" * 64
    elif change == "target":
        payload["profile"]["name"] = "other"
    else:
        payload["spec"]["options"]["target_profile"]["digest"] = "0" * 64
    try:
        with pytest.raises(AgentTaskError):
            worker._dispatch("configure", payload)
        assert worker._spec is None and not calls
        assert worker._dispatch("configure", profile_request(path, digest))["ready"]
    finally:
        worker.close()


@pytest.mark.parametrize("platform,bits", [("linux", 64), ("darwin", 64), ("win32", 32)])
def test_host_platform_refusal_precedes_helper_acquisition(tmp_path, monkeypatch, platform, bits):
    target = NativeFixtureTarget(AgentTargetProfile.from_dict(config(tmp_path)))
    monkeypatch.setattr(target_config, "sys", SimpleNamespace(platform=platform, maxsize=2**(bits-1)-1))
    with pytest.raises(AgentTaskError, match="64-bit Windows"):
        target_config.check_host_platform(target._profile)
    assert target._channel is None


def test_registered_fixture_roundtrip_completion_and_live_disablement(tmp_path, monkeypatch):
    value = config(tmp_path)
    channels = []

    class Channel:
        def __init__(self, argv, **_kwargs):
            image = load_fixture_image(argv[-3], argv[-1])
            target, self.child, self.calls, *_ = injected(image)
            self.worker = FixtureWorker(BytesIO(), BytesIO(), target=target,
                reference=value["settings"], target_id=image.target_id)
            self.retired = False
            channels.append(self)

        def request(self, operation, payload, *, check, **_kwargs):
            check()
            result = self.worker._dispatch(operation, payload)
            check()
            return result

        def close(self):
            self.worker.close()
            self.retired = True

    monkeypatch.setattr(native_target, "owned_channel", Channel)
    runtime = AgentRuntime(tmp_path / "runtime.sqlite")
    try:
        runtime.target_profiles.control("register", value)
        runtime._targets["fixture"]._resource_path = tmp_path / "fixture.lock"
        task = runtime.submit(spec())
        frame = runtime.observe(task.task_id)
        result = runtime.act(task.task_id, {"tool": FIXTURE_COMMAND, "observation_id": frame.observation_id,
                                           "arguments": {"document_id": 42, "job_status": "done"}})
        assert result.status == "confirmed"
        assert runtime.finish(task.task_id).state == "succeeded"
        assert channels[0].retired and channels[0].child.retired
        next_task = runtime.submit(replace(spec(), goal="disable before effect"))
        runtime.observe(next_task.task_id)
        runtime.target_profiles.control("disable", {"name": "fixture"})
        assert runtime.get(next_task.task_id).state == "paused"
        assert channels[-1].retired and channels[-1].child.retired
        with pytest.raises(AgentTaskError):
            runtime.observe(next_task.task_id)
    finally:
        runtime.close()


@pytest.mark.parametrize("value, local", [
    ("C:/fixtures/fixture.exe", True), ('C:\\fixtures\\fixture.exe', True),
    ('\\\\host\\share\\fixture.exe', False), ("//host/share/fixture.exe", False), ('\\\\.\\pipe\\fixture', False),
    ('\\\\?\\C:\\fixture.exe', False), ('C:\\a\\..\\fixture.exe', False),
    ("fixture.exe", False), ('\\fixture.exe', False),
], ids=["slash", "backslash", "unc", "unc-slash", "pipe", "device", "parent", "relative", "rootless"])
def test_artifact_paths_must_be_local_drive_paths(value, local):
    # A UNC path would send the host account's credentials to that server, and
    # a pipe name connects to whoever created the pipe first.
    assert is_local_absolute(value, PureWindowsPath(value)) is local
