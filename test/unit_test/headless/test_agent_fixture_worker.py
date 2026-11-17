"""Validate packaged fixture delivery with static PE bytes and injected native owners only."""
from dataclasses import replace
import hashlib
from io import BytesIO
import json
import struct
from types import SimpleNamespace

import pytest

from je_auto_control.utils.agent_runtime import fixture_deployment, fixture_worker, target_config
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.target_config import AgentTargetProfile
from je_auto_control.utils.process_memory.models import ProcessIdentity
from headless.test_agent_fixture_readiness import spec
from headless.test_agent_fixture_target import setup
from headless.test_process_memory_pe_image import baseline


@pytest.fixture(autouse=True)
def windows_profile_host(monkeypatch):
    monkeypatch.setattr(target_config, "sys", SimpleNamespace(platform="win32", maxsize=2**63-1))


def deployment(tmp_path, **changes):
    raw = bytes(baseline())
    image = tmp_path / "owned.exe"
    image.write_bytes(raw)
    value = {"schema": 1, "host": "owned-host", "target": "fixture", "image": str(image),
             "image_sha256": hashlib.sha256(raw).hexdigest(), "read_timeout": 5} | changes
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def profile_request(path, digest, definition=None):
    profile = AgentTargetProfile(name="fixture", kind="fixture", allowed_tools=spec().allowed_tools,
                                 settings={"config_path": str(path), "config_sha256": digest})
    definition = definition or spec()
    definition = replace(definition, options={"target_profile": {"name": profile.name, "digest": profile.digest}})
    return {"spec": definition.to_dict(), "owner": {}, "profile": profile.to_dict()}


def test_static_deployment_pins_bytes_and_generates_fresh_identity(tmp_path):
    path, digest = deployment(tmp_path)
    first = fixture_deployment.load_fixture_image(str(path), digest)
    second = fixture_deployment.load_fixture_image(str(path), digest)
    assert first.baseline == bytes(baseline())
    assert first.pin.session != second.pin.session and first.challenge != second.challenge
    assert (first.pin.executable, first.pin.version, first.target_id) == ("fixture", "1", "fixture")
    assert first.path not in repr(first) and first.challenge.hex() not in repr(first)


@pytest.mark.parametrize("change", [
    {"schema": True}, {"schema": 2}, {"pid": 42}, {"address": 8192}, {"argv": []},
    {"session": "reused"}, {"challenge": "chosen"}, {"target": "../bad"},
    {"host": "bad host"}, {"image": "relative.exe"}, {"image_sha256": "0" * 64},
    {"read_timeout": True}, {"read_timeout": 0}, {"read_timeout": 61},
    {"read_timeout": float("nan")}, {"read_timeout": 10**400},
])
def test_unknown_scope_or_invalid_deployment_never_constructs_target(tmp_path, change):
    path, digest = deployment(tmp_path, **change)
    with pytest.raises(AgentTaskError, match="^fixture deployment is invalid$"):
        fixture_worker.serve(str(path), digest, BytesIO(), BytesIO(),
                             target_factory=lambda _: pytest.fail("target constructed"))


def test_config_pin_is_checked_before_following_image_path(tmp_path, monkeypatch):
    path, _ = deployment(tmp_path)
    original = fixture_deployment._read
    reads = []

    def read(artifact, limit):
        reads.append(artifact)
        return original(artifact, limit)

    monkeypatch.setattr(fixture_deployment, "_read", read)
    with pytest.raises(AgentTaskError):
        fixture_deployment.load_fixture_image(str(path), "0" * 64)
    assert reads == [path]


@pytest.mark.parametrize("raw", [b"[" * 2000 + b"]" * 2000, b" " * 16385, b"[]"])
def test_bounded_json_rejects_duplicate_keys_deep_nesting_and_oversize(tmp_path, raw):
    path = tmp_path / "invalid.json"
    path.write_bytes(raw)
    with pytest.raises(AgentTaskError, match="^fixture deployment is invalid$"):
        fixture_deployment.load_fixture_image(str(path), hashlib.sha256(raw).hexdigest())


def test_duplicate_field_in_otherwise_valid_deployment_is_rejected(tmp_path):
    path, _ = deployment(tmp_path)
    raw = path.read_bytes().replace(b'"schema": 1', b'"schema": 1, "schema": 1')
    path.write_bytes(raw)
    with pytest.raises(AgentTaskError):
        fixture_deployment.load_fixture_image(str(path), hashlib.sha256(raw).hexdigest())


def test_oversize_image_is_refused_before_native_construction(tmp_path):
    path, digest = deployment(tmp_path)
    image = tmp_path / "owned.exe"
    with image.open("r+b") as stream:
        stream.truncate((64 << 20) + 1)
    with pytest.raises(AgentTaskError):
        fixture_worker.serve(str(path), digest, BytesIO(), BytesIO(),
                             target_factory=lambda _: pytest.fail("native constructor"))


def injected(image):
    target, kernel, channel, calls, provider, lease, watch = setup()
    kernel.image_path = image.path
    target._image = image
    target._owners.launcher._launcher._arguments = ("--rpc", "--challenge", image.challenge.hex())
    provider.identity = lambda: ProcessIdentity(image.pin.host, image.pin.session, 42, kernel.birth,
                                                "fixture", "1", "x64", 64)
    struct.pack_into("16s", provider.memory, 0x2208, image.challenge)
    return target, channel, calls, lease, watch


@pytest.mark.parametrize("mode", ["eof", "bootstrap", "managed", "wrong_scope", "revoked_owner"])
def test_packaged_worker_uses_managed_acquisition_and_eof_cleanup(tmp_path, mode):
    path, digest = deployment(tmp_path)
    owners = []
    definition = spec()
    if mode == "wrong_scope":
        definition = replace(definition, target="another-target")
    requests = []
    if mode != "eof":
        requests.append({"id": "b", "operation": "bootstrap", "payload": {}})
    if mode in {"managed", "wrong_scope", "revoked_owner"}:
        owner = ({"user_id": "missing", "role": "operator", "store_path": str(tmp_path / "users.json")}
                 if mode == "revoked_owner" else {})
        requests.extend([{"id": "c", "operation": "configure", "payload":
                          profile_request(path, digest, definition) | {"owner": owner}},
            {"id": "o", "operation": "observe", "payload": {}}])
    source = BytesIO(b"".join(json.dumps(request).encode() + b"\n" for request in requests))
    sink = BytesIO()

    def factory(image):
        owner = injected(image)
        owners.append(owner)
        return owner[0]

    fixture_worker.serve(str(path), digest, source, sink, target_factory=factory)
    _, channel, calls, lease, watch = owners[0]
    replies = [json.loads(line) for line in sink.getvalue().splitlines()]
    if mode == "managed":
        assert len(calls) == 1 and channel.retired
        captured = replies[-1]["result"]
        assert captured["status"] == "complete"
        assert captured["sources"]["process_memory"]["snapshot"]["fields"] == {
            "document_id": 7, "job_status": "ready"}
    else:
        assert not calls
        if mode in {"wrong_scope", "revoked_owner"}:
            assert "error" in replies[1]
    assert not lease.pending_cleanup and not watch.pending_cleanup


@pytest.mark.parametrize("platform,bits", [("linux", 64), ("darwin", 64), ("win32", 32)])
def test_native_factory_rejects_unsupported_hosts_before_constructors(tmp_path, monkeypatch, platform, bits):
    path, digest = deployment(tmp_path)
    image = fixture_deployment.load_fixture_image(str(path), digest)
    monkeypatch.setattr(fixture_worker, "sys", SimpleNamespace(platform=platform, maxsize=2**(bits-1)-1))
    monkeypatch.setattr(fixture_worker, "OwnedChannelLauncher", lambda *_a, **_k: pytest.fail("native constructor"))
    with pytest.raises(AgentTaskError, match="64-bit Windows"):
        fixture_worker.create_target(image)


def test_native_factory_has_only_fixed_rpc_arguments_and_no_acquisition(tmp_path, monkeypatch):
    path, digest = deployment(tmp_path)
    image = fixture_deployment.load_fixture_image(str(path), digest)
    target, *_ = injected(image)
    launcher = target._owners.launcher
    arguments = []

    def construct(argv):
        arguments.append(argv)
        return launcher

    observers = iter((target._owners.lease, target._owners.observer))
    monkeypatch.setattr(fixture_worker, "sys", SimpleNamespace(platform="win32", maxsize=2**63-1))
    monkeypatch.setattr(fixture_worker, "OwnedChannelLauncher", construct)
    monkeypatch.setattr(fixture_worker, "WindowsImageObserver", lambda: next(observers))
    result = fixture_worker.create_target(image)
    assert arguments == [("--rpc", "--challenge", image.challenge.hex())]
    assert launcher._channel is None
    result.cleanup()


def test_cli_startup_errors_are_fixed_and_never_protocol_output(tmp_path, capsys):
    missing = str(tmp_path / "private-missing.json")
    assert fixture_worker.main(["--config", missing, "--config-sha256", "0" * 64]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err == "fixture worker failed\n"


def test_protocol_failure_after_readiness_retires_acquired_fixture(tmp_path):
    path, digest = deployment(tmp_path)
    owners = []

    def factory(image):
        owner = injected(image)
        owners.append(owner)
        return owner[0]

    configure = {"id": "c", "operation": "configure", "payload": profile_request(path, digest)}
    source = BytesIO(json.dumps(configure).encode() + b"\n{invalid\n")
    with pytest.raises(ValueError):
        fixture_worker.serve(str(path), digest, source, BytesIO(), target_factory=factory)
    _, channel, calls, lease, watch = owners[0]
    assert len(calls) == 1 and channel.retired
    assert not lease.pending_cleanup and not watch.pending_cleanup
