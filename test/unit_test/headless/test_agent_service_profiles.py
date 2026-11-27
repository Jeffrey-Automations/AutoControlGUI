"""Verify pinned service profiles without acquiring real SCM or desktop resources."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime import native_target, service_deployment, target_config
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.context import TaskOperation, operation_scope
from je_auto_control.utils.agent_runtime.service_deployment import load_service_deployment
from je_auto_control.utils.agent_runtime.service_entrypoint import PinnedServiceWorker, serve
from je_auto_control.utils.agent_runtime.service_native_target import NativeServiceTarget
from je_auto_control.utils.agent_runtime.service_scope import service_scope
from je_auto_control.utils.agent_runtime.service_target import ManagedServiceTarget
from je_auto_control.utils.agent_runtime.target_config import AgentTargetProfile
from je_auto_control.utils.rbac.authorization import AuthorizationContext, authorization_scope
from headless.test_agent_service_control import ControlApi

HELPER = Path(__file__).resolve().parents[2] / "fixtures" / "service_profile_helper.py"


def config(tmp_path, *, name="service", key="OwnedFixture", operations=None, **changes):
    data = {"schema": 1, "kind": "service", "target": name, "service_key": key,
            "operations": ["start", "stop"] if operations is None else operations} | changes
    path = tmp_path / (name + ".json")
    path.write_text(json.dumps(data), encoding="utf-8")
    return {"name": name, "kind": "service", "allowed_tools": ["AC_service_start", "AC_service_stop"],
            "roots": [], "apps": [], "settings": {"config_path": str(path),
            "config_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "service_key": key}}


def task(name="service", tool="AC_service_start", **changes):
    return {"goal": "verify service", "target": name, "allowed_tools": [tool],
            "success_criteria": [{"kind": "service_state", "tool": tool,
                                  "state": "running" if tool.endswith("start") else "stopped"}],
            "budget": {"action_seconds": 3}, **changes}


def load(value):
    return load_service_deployment(value["settings"]["config_path"], value["settings"]["config_sha256"])


def worker(value):
    deployment = load(value)
    api = ControlApi()
    api.state = 1
    target = ManagedServiceTarget(deployment.target_id, value["settings"]["config_sha256"],
        service_scope(deployment.service_key), api.controller(), allowed=deployment.allowed)
    reference = {key: value["settings"][key] for key in ("config_path", "config_sha256")}
    return PinnedServiceWorker(BytesIO(), BytesIO(), target=target,
                               deployment=deployment, reference=reference), api


def payload(value):
    profile = AgentTargetProfile.from_dict(value)
    return {"spec": task(profile.name, options={"target_profile": {"name": profile.name, "digest": profile.digest}}),
            "profile": profile.to_dict(), "owner": {}}


@pytest.fixture(autouse=True)
def windows_host(monkeypatch):
    monkeypatch.setattr(target_config, "sys", SimpleNamespace(platform="win32", maxsize=2**63 - 1))


@pytest.mark.parametrize("change", [{"schema": True}, {"schema": 2}, {"kind": "fixture"},
    {"argv": []}, {"background_verified": True}, {"machine": "remote"}, {"operations": []},
    {"operations": ["start", "start"]}, {"operations": ["restart"]}, {"operations": [True]},
    {"operations": "start"}, {"operations": [{}]}, {"target": "../bad"}, {"service_key": "Owned\u200bFixture"}])
def test_closed_deployment_refuses_before_factory(tmp_path, change):
    value = config(tmp_path, **change)
    with pytest.raises(AgentTaskError, match="service deployment is invalid"):
        serve(value["settings"]["config_path"], value["settings"]["config_sha256"], BytesIO(), BytesIO(),
              target_factory=lambda *_: pytest.fail("constructed owner"))


def test_pins_duplicate_keys_and_bounds_fail_before_factory(tmp_path):
    value = config(tmp_path)
    settings = value["settings"]
    assert load(value).service_key == "OwnedFixture"
    for raw in (b'{"schema":1,"schema":1}', b"x" * 16385):
        Path(settings["config_path"]).write_bytes(raw)
        with pytest.raises(AgentTaskError):
            load_service_deployment(settings["config_path"], hashlib.sha256(raw).hexdigest())
    with pytest.raises(AgentTaskError):
        load(value)


@pytest.mark.parametrize("change", [{"roots": ["C:/owned"]}, {"apps": ["app.exe"]},
    {"allowed_tools": ["AC_write"]}, {"settings": {}},
    {"settings": {"config_path": "relative", "config_sha256": "a" * 64, "service_key": "Owned"}}])
def test_profile_refuses_other_resource_authority(tmp_path, change):
    with pytest.raises(AgentTaskError):
        AgentTargetProfile.from_dict(config(tmp_path) | change)


def test_registration_reload_and_probe_do_not_open_missing_deployment(tmp_path, monkeypatch):
    value = config(tmp_path)
    Path(value["settings"]["config_path"]).unlink()
    monkeypatch.setattr(native_target, "owned_channel", lambda *_a, **_k: pytest.fail("helper launched"))
    monkeypatch.setattr(service_deployment, "load_deployment", lambda *_: pytest.fail("config read"))
    database = tmp_path / "runtime.db"
    runtime = AgentRuntime(database)
    try:
        with authorization_scope(AuthorizationContext("operator", "operator")), pytest.raises(AgentTaskError):
            runtime.target_profiles.control("register", value)
        runtime.target_profiles.control("register", value)
        for key in ("config_path", "config_sha256", "service_key", "helper_python"):
            with pytest.raises(AgentTaskError, match="host configuration"):
                runtime.submit(task(options={key: "other"}))
        assert runtime._targets["service"].probe() == {"status": "not_supported", "native_evidence": "not_recorded"}
        runtime.target_profiles.control("probe", {"name": "service"})
        runtime.target_profiles.control("disable", {"name": "service"})
    finally:
        runtime.close()
    restored = AgentRuntime(database)
    try:
        adapter = restored._targets["service"]
        assert adapter._channel is None
        assert adapter._argv[1:5] == ("-I", "-u", "-m", "je_auto_control.utils.agent_runtime.service_entrypoint")
        with pytest.raises(AgentTaskError, match="disabled"):
            restored.submit(task())
        assert restored.target_profiles.control("get", {"name": "service"})["profile"] == value
    finally:
        restored.close()


@pytest.mark.parametrize("change", ["profile_key", "config_path", "config_sha256", "pin", "tools", "owner",
                                  "presence", "missing_profile", "profile_kind", "target", "mode"])
def test_invalid_preflight_does_not_poison_valid_configuration(tmp_path, change):
    value = config(tmp_path, operations=["start"])
    value["allowed_tools"] = ["AC_service_start"]
    instance, api = worker(value)
    bad = payload(value)
    if change in {"profile_key", "config_path", "config_sha256"}:
        key = "service_key" if change == "profile_key" else change
        bad["profile"]["settings"][key] = "Other" if key == "service_key" else (
            "b" * 64 if key == "config_sha256" else str(tmp_path / "elsewhere.json"))
        p = AgentTargetProfile.from_dict(bad["profile"])
        bad["spec"]["options"]["target_profile"]["digest"] = p.digest
    elif change == "pin":
        bad["spec"]["options"]["target_profile"]["digest"] = "b" * 64
    elif change == "tools":
        bad["profile"]["allowed_tools"] += ["AC_service_stop"]
        bad["spec"]["options"]["target_profile"]["digest"] = AgentTargetProfile.from_dict(bad["profile"]).digest
    elif change == "owner":
        bad["owner"] = {"user_id": [], "role": "admin", "store_path": None}
    elif change == "presence":
        bad["presence"] = {}
    elif change == "missing_profile":
        del bad["profile"]
    elif change == "profile_kind":
        bad["profile"]["kind"] = "files"
    elif change == "target":
        bad["spec"]["target"] = "other"
    else:
        bad["spec"]["mode"] = "ollama"
    with pytest.raises(AgentTaskError):
        instance._dispatch("configure", bad)
    assert instance._spec is None and instance._owner is None
    instance._dispatch("configure", payload(value))
    assert instance._spec.target == "service"
    instance._dispatch("cleanup", {"keys": [], "buttons": []})
    assert api.OpenSCManagerW.calls == []


@pytest.mark.parametrize("rewrite_pin", [False, True])
def test_configured_worker_pins_full_profile_even_for_unchanged_task_tools(tmp_path, rewrite_pin):
    value = config(tmp_path)
    instance, _ = worker(value)
    original = payload(value)
    instance._dispatch("configure", original)
    changed = payload(value)
    changed["profile"]["allowed_tools"] = ["AC_service_start"]
    if rewrite_pin:
        changed["spec"]["options"]["target_profile"]["digest"] = AgentTargetProfile.from_dict(changed["profile"]).digest
    with pytest.raises(AgentTaskError):
        instance._dispatch("configure", changed)
    assert instance._spec.options["target_profile"] == original["spec"]["options"]["target_profile"]
    instance._dispatch("cleanup", {"keys": [], "buttons": []})


def test_wrong_platform_fails_before_scope_or_launch(tmp_path, monkeypatch):
    value = config(tmp_path)
    instance, _ = worker(value)
    proxy = NativeServiceTarget.from_profile(AgentTargetProfile.from_dict(value))
    monkeypatch.setattr(target_config, "sys", SimpleNamespace(platform="linux", maxsize=2**63 - 1))
    monkeypatch.setattr(native_target, "owned_channel", lambda *_a, **_k: pytest.fail("launched"))
    with pytest.raises(AgentTaskError, match="Windows"):
        instance._dispatch("configure", payload(value))
    assert instance._spec is None
    spec = AgentTaskSpec.from_dict(task())
    with operation_scope(TaskOperation(spec, lambda: None, None)), pytest.raises(AgentTaskError, match="Windows"):
        proxy.ready(spec)


def test_profile_ceiling_applies_to_direct_proxy_readiness(tmp_path):
    value = config(tmp_path)
    value["allowed_tools"] = ["AC_service_start"]
    proxy = NativeServiceTarget.from_profile(AgentTargetProfile.from_dict(value))
    with pytest.raises(AgentTaskError, match="tools exceed"):
        proxy.check_spec(AgentTaskSpec.from_dict(task(tool="AC_service_stop")))


def injected(runtime, value, fault="none", initial=1):
    runtime.target_profiles.control("register", value)
    adapter = runtime._targets[value["name"]]
    settings = value["settings"]
    adapter._argv = (sys.executable, "-u", str(HELPER), settings["config_path"],
                     settings["config_sha256"], fault, str(initial))
    return adapter


@pytest.mark.parametrize("tool,initial", [("AC_service_start", 1), ("AC_service_stop", 4)])
@pytest.mark.parametrize("fault,status", [("none", "passed"), ("no_effect", "failed")])
def test_hidden_fixed_entrypoint_runs_profile_and_retires(tmp_path, tool, initial, fault, status):
    runtime = AgentRuntime(tmp_path / "runtime.db")
    try:
        value = config(tmp_path)
        value["settings"]["service_key"] = "ownedfixture"
        adapter = injected(runtime, value, fault, initial)
        handle = runtime.submit(task(tool=tool)).task_id
        frame = runtime.observe(handle)
        channel = adapter._channel
        result = runtime.act(handle, {"tool": tool, "observation_id": frame.observation_id})
        assert result.result["accepted"] is True
        assert runtime.finish(handle).verification == ({"kind": "service_state", "status": status},)
        runtime.target_profiles.control("disable", {"name": "service"})
    finally:
        runtime.close()
    assert channel.retired and channel._process.poll() is not None


def test_same_service_alias_profiles_share_lease_across_databases(tmp_path):
    from je_auto_control.utils.agent_runtime.errors import AgentControlBusy
    first, second = AgentRuntime(tmp_path / "first.db"), AgentRuntime(tmp_path / "second.db")
    try:
        left = injected(first, config(tmp_path, name="left", key="OwnedFixture"))
        right = injected(second, config(tmp_path, name="right", key="ownedfixture"))
        assert left._resource_path == right._resource_path
        a, b = first.submit(task("left")).task_id, second.submit(task("right")).task_id
        first.observe(a)
        with pytest.raises(AgentControlBusy):
            second.observe(b)
        assert right._channel is None
    finally:
        first.close()
        second.close()


def test_entrypoint_help_is_inert():
    result = subprocess.run([sys.executable, "-m", "je_auto_control.utils.agent_runtime.service_entrypoint", "--help"],
                            capture_output=True, timeout=15, check=False)
    assert result.returncode == 0 and b"--config-sha256" in result.stdout
