"""Verify pinned read-only UI worker delivery using injected sources and private in-memory IPC."""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from types import SimpleNamespace

import pytest

from je_auto_control.utils.agent_runtime import target_config, uia_deployment, uia_worker
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.observation_report import REPORT_VERSION
from je_auto_control.utils.agent_runtime.target_config import AgentTargetProfile
from je_auto_control.utils.agent_runtime.uia_native_target import NativeUiaFixtureTarget
from je_auto_control.utils.agent_runtime.uia_target import UIA_FIELDS
from headless.test_agent_uia_target import target


@pytest.fixture(autouse=True)
def windows_profile_host(monkeypatch):
    monkeypatch.setattr(target_config, "sys", SimpleNamespace(platform="win32", maxsize=2**63-1))


def deployment(tmp_path, monkeypatch):
    raw = b"owned injected UI image"
    image = "C:\\owned\\uia_fixture.exe"
    data = {"schema": 1, "kind": "uia_fixture", "host": "owned-host", "target": "fixture",
            "image": image, "image_sha256": hashlib.sha256(raw).hexdigest(),
            "max_image_bytes": 64 << 20, "attestation_timeout": 5}
    path = tmp_path / "uia.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    def read(artifact, limit):
        assert str(artifact) == image and limit == 64 << 20
        return raw
    monkeypatch.setattr(uia_deployment, "read_artifact", read)
    return {"config_path": str(path), "config_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def profile_request(reference):
    profile = AgentTargetProfile(name="fixture", kind="uia_fixture", allowed_tools=(), settings=reference)
    spec = {"goal": "inspect owned UI", "target": "fixture", "allowed_tools": [],
            "success_criteria": [{"kind": "actions_complete"}],
            "options": {"target_profile": {"name": profile.name, "digest": profile.digest}}}
    return profile, {"spec": spec, "owner": {}, "profile": profile.to_dict()}


def worker(reference):
    adapter, closed = target()
    acquisitions = []
    original = adapter._acquire
    def acquire(check):
        acquisitions.append(True)
        return original(check)
    adapter._acquire = acquire
    result = uia_worker.UiaFixtureWorker(BytesIO(), BytesIO(), target=adapter,
                                       reference=reference, target_id="fixture")
    return result, acquisitions, closed


@pytest.mark.parametrize("mode", ["eof", "bootstrap", "managed", "invalid_stream"])
def test_packaged_worker_acquires_only_after_configuration_and_cleans_eof(tmp_path, monkeypatch, mode):
    reference = deployment(tmp_path, monkeypatch)
    _, payload = profile_request(reference)
    requests = []
    if mode != "eof":
        requests.append({"id": "b", "operation": "bootstrap", "payload": {}})
    if mode in {"managed", "invalid_stream"}:
        requests.extend([{"id": "c", "operation": "configure", "payload": payload},
                         {"id": "o", "operation": "observe", "payload": {}}])
    wire = b"".join(json.dumps(item).encode() + b"\n" for item in requests)
    if mode == "invalid_stream":
        wire += b"{invalid\n"
    acquired, closed = [], []
    def factory(image):
        assert (image.target_id, image.pin.executable, image.pin.version) == ("fixture", "uia-fixture", "1")
        adapter, cleaned = target()
        original = adapter._acquire
        def acquire(check):
            acquired.append(True)
            return original(check)
        adapter._acquire = acquire
        closed.append(cleaned)
        return adapter
    sink = BytesIO()
    args = (reference["config_path"], reference["config_sha256"], BytesIO(wire), sink)
    if mode == "invalid_stream":
        with pytest.raises(ValueError):
            uia_worker.serve(*args, target_factory=factory)
    else:
        uia_worker.serve(*args, target_factory=factory)
    assert closed and closed[0]
    assert bool(acquired) == (mode in {"managed", "invalid_stream"})
    replies = [json.loads(line) for line in sink.getvalue().splitlines()]
    if mode in {"managed", "invalid_stream"}:
        report = replies[-1]["result"]
        assert report["status"] == "partial" and report["report_version"] == REPORT_VERSION
        fields = report["sources"]["uia"]["partial"]["fields"]
        assert fields["empty"] == "" and fields["enabled"] is False


@pytest.mark.parametrize("change", ["config", "profile_name", "spec_target", "profile_pin", "tools"])
def test_wrong_configuration_is_refused_before_worker_scope_mutation(tmp_path, monkeypatch, change):
    reference = deployment(tmp_path, monkeypatch)
    _, payload = profile_request(reference)
    candidate = deepcopy(payload)
    if change == "config":
        candidate["profile"]["settings"]["config_sha256"] = "0" * 64
    elif change == "profile_name":
        candidate["profile"]["name"] = "another-ui"
    elif change == "spec_target":
        candidate["spec"]["target"] = "another-ui"
    elif change == "profile_pin":
        candidate["spec"]["options"]["target_profile"]["digest"] = "0" * 64
    else:
        candidate["spec"]["allowed_tools"] = ["AC_fixture_set_state"]
    instance, acquired, _ = worker(reference)
    try:
        with pytest.raises(AgentTaskError):
            instance._dispatch("configure", candidate)
        assert instance._spec is None and instance._owner is None and not acquired
        assert instance._dispatch("configure", payload)["ready"]
    finally:
        instance.close()


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("operation", ["perform", "perform_grounded"])
def test_worker_refuses_effect_requests_before_generic_dispatch(tmp_path, monkeypatch, configured, operation):
    reference = deployment(tmp_path, monkeypatch)
    _, payload = profile_request(reference)
    instance, acquired, _ = worker(reference)
    try:
        if configured:
            instance._dispatch("configure", payload)
        with pytest.raises(AgentTaskError, match="read-only"):
            instance._dispatch(operation, {})
        assert len(acquired) == int(configured)
    finally:
        instance.close()


def test_proxy_has_fixed_argv_matching_bootstrap_and_no_effect_or_probe_ipc(tmp_path, monkeypatch):
    reference = deployment(tmp_path, monkeypatch)
    profile, _ = profile_request(reference)
    proxy = NativeUiaFixtureTarget(profile)
    assert proxy._argv[1:5] == ("-I", "-u", "-m", "je_auto_control.utils.agent_runtime.uia_worker")
    assert proxy._resource_path.name == "uia-fixture-" + profile.digest + ".lock"
    monkeypatch.setattr(proxy, "_request", lambda *_a, **_kw: pytest.fail("effect IPC"))
    assert proxy.probe() == {"status": "not_supported", "native_evidence": "not_recorded"}
    with pytest.raises(AgentTaskError, match="read-only"):
        proxy._send_grounded("AC_fixture_set_state", {}, {}, "id")
    instance, _, _ = worker(reference)
    try:
        bootstrap = instance._bootstrap()
        assert proxy._supports_bootstrap(bootstrap)
        assert bootstrap["semantic_sources"] == ["uia"]
        assert bootstrap["semantic_fields"] == list(UIA_FIELDS)
        for key, value in (("version", True), ("version", 2), ("config_sha256", "0" * 64),
                           ("target", "another-ui")):
            modified = deepcopy(bootstrap)
            modified["uia_fixture"][key] = value
            assert not proxy._supports_bootstrap(modified)
    finally:
        instance.close()


def test_bad_config_pin_never_constructs_target(tmp_path, monkeypatch):
    reference = deployment(tmp_path, monkeypatch)
    with pytest.raises(AgentTaskError):
        uia_worker.serve(reference["config_path"], "0" * 64, BytesIO(), BytesIO(),
                         target_factory=lambda _: pytest.fail("constructed native owner"))


@pytest.mark.parametrize("platform,bits", [("linux", 64), ("win32", 32)])
def test_host_platform_refusal_precedes_scope_mutation(tmp_path, monkeypatch, platform, bits):
    reference = deployment(tmp_path, monkeypatch)
    _, payload = profile_request(reference)
    instance, acquired, _ = worker(reference)
    monkeypatch.setattr(target_config, "sys", SimpleNamespace(platform=platform, maxsize=2**(bits-1)-1))
    try:
        with pytest.raises(AgentTaskError, match="64-bit Windows"):
            instance._dispatch("configure", payload)
        assert instance._spec is None and instance._owner is None and not acquired
    finally:
        instance.close()
