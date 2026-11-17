"""Verify smoke reporting with static artifacts and injected owned-target assembly."""
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

import pytest

from je_auto_control.utils.exception.control_signals import OperationCancelledError
from headless.test_agent_fixture_target import setup
from headless.test_process_memory_pe_image import baseline

SCRIPT = Path(__file__).resolve().parents[2] / "fixtures" / "native_memory" / "acceptance.py"
SPEC = importlib.util.spec_from_file_location("native_memory_acceptance", SCRIPT)
acceptance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = acceptance
SPEC.loader.exec_module(acceptance)


def build(tmp_path):
    raw = bytes(baseline())
    digest = hashlib.sha256(raw).hexdigest()
    source = SCRIPT.with_name("fixture.c").read_bytes()
    (tmp_path / "fixture.c").write_bytes(source)
    (tmp_path / "memory_fixture.exe").write_bytes(raw)
    (tmp_path / "manifest.json").write_text(json.dumps({
        "schema": 1, "architecture": "x64", "crt": "static",
        "imported_dlls": ["bcrypt.dll", "kernel32.dll"],
        "source_sha256": hashlib.sha256(source).hexdigest(), "image_sha256": digest}), encoding="utf-8")
    return digest


def test_default_cli_reads_only_static_artifacts(tmp_path, monkeypatch, capsys):
    digest = build(tmp_path)
    monkeypatch.setattr(acceptance, "run_smoke", lambda _: pytest.fail("unexpected execution"))
    assert acceptance.main(["--build", str(tmp_path), "--sha256", digest]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["execution"] == "not_run" and value["checked_bytes"] == 4608
    assert value["checks"] == {} and value["full_native_acceptance"] == "not_verified"
    assert str(tmp_path) not in json.dumps(value)


@pytest.mark.parametrize("change", ["pin", "image", "source", "schema", "imports", "oversize"])
def test_preparation_refuses_mismatched_or_unbounded_inventory(tmp_path, change):
    digest = build(tmp_path)
    if change == "pin":
        digest = "0" * 64
    elif change in {"image", "source"}:
        name = "memory_fixture.exe" if change == "image" else "fixture.c"
        with (tmp_path / name).open("ab") as stream:
            stream.write(b"changed")
    else:
        manifest = tmp_path / "manifest.json"
        value = json.loads(manifest.read_text())
        if change == "schema":
            value["schema"] = True
        elif change == "imports":
            value["imported_dlls"].append("unexpected.dll")
        else:
            value["padding"] = "x" * 16384
        manifest.write_text(json.dumps(value))
    with pytest.raises((ValueError, acceptance.MemoryObservationError)):
        acceptance.prepare(tmp_path, digest)


def test_deep_manifest_returns_closed_cli_failure(tmp_path, capsys):
    digest = build(tmp_path)
    (tmp_path / "manifest.json").write_text("[" * 1100 + "0" + "]" * 1100)
    assert acceptance.main(["--build", str(tmp_path), "--sha256", digest]) == 1
    value = json.loads(capsys.readouterr().out)
    assert value == {"schema": 1, "execution": "not_run", "failure": "preparation_failed"}


def test_decoder_recursion_failure_is_normalized(tmp_path, monkeypatch):
    digest = build(tmp_path)

    def too_deep(_):
        raise RecursionError("PRIVATE decoder detail")

    monkeypatch.setattr(acceptance.json, "loads", too_deep)
    with pytest.raises(ValueError, match="invalid build inventory"):
        acceptance.prepare(tmp_path, digest)


def injected():
    target, kernel, channel, _, provider, *_ = setup()
    target._image = replace(target._image, read_timeout=60)
    struct.pack_into("<I12s", provider.memory, 0x2300, 17, b"ready")
    prepared = acceptance.PreparedFixture(target._image, 4608, "a" * 64)
    return target, kernel, channel, provider, prepared


def test_smoke_uses_actual_runtime_readback_and_keeps_unverified_boundaries():
    target, _, channel, _, prepared = injected()
    result = acceptance.run_smoke(prepared, target_factory=lambda _: target)
    assert result["execution"] == "passed" and result["cleanup_confirmed"]
    assert result["checks"] == {"initial_state": True, "operation_receipt": True,
                                "independent_readback": True, "runtime_completion": True}
    assert channel.retired
    assert all(result[name] == "not_verified" for name in (
        "dependency_trust", "foreground_noninterference", "fault_matrix", "full_native_acceptance"))
    rendered = json.dumps(result)
    assert prepared.image.challenge.hex() not in rendered and prepared.image.path not in rendered


def test_successful_receipt_without_mutation_fails_independent_readback():
    target, _, channel, provider, prepared = injected()
    original = channel.request

    def no_effect(operation, value, **kwargs):
        before = bytes(provider.memory)
        reply = original(operation, value, **kwargs)
        provider.memory[:] = before
        return reply

    channel.request = no_effect
    result = acceptance.run_smoke(prepared, target_factory=lambda _: target)
    assert result["execution"] == "failed" and result["cleanup_confirmed"]
    assert result["checks"] == {"initial_state": True, "operation_receipt": True}


def test_image_changed_after_preparation_cannot_launch():
    target, kernel, channel, _, prepared = injected()
    kernel.data = b"changed image"
    result = acceptance.run_smoke(prepared, target_factory=lambda _: target)
    assert result["execution"] == "failed" and result["failure"] == "unsupported"
    assert result["checks"] == {} and channel.closed == 0


def test_failure_report_does_not_echo_exception_details():
    target, _, _, _, prepared = injected()

    def fail(**_):
        raise RuntimeError("PRIVATE_ADDRESS_TOKEN")

    target.start = fail
    result = acceptance.run_smoke(prepared, target_factory=lambda _: target)
    assert result["failure"] == "smoke_failed" and result["cleanup_confirmed"]
    assert "PRIVATE" not in json.dumps(result)


def test_cancellation_is_preserved_after_cleanup():
    target, _, channel, _, prepared = injected()
    signal = OperationCancelledError("stop")
    original = target.start

    def cancel(**kwargs):
        original(**kwargs)
        raise signal

    target.start = cancel
    with pytest.raises(OperationCancelledError) as caught:
        acceptance.run_smoke(prepared, target_factory=lambda _: target)
    assert caught.value is signal and channel.retired


def test_cleanup_retry_is_recorded_without_repeating_the_command():
    target, _, channel, _, prepared = injected()
    original = target.cleanup
    original_start = target.start
    calls = []

    def retry():
        calls.append(1)
        if len(calls) == 1:
            raise OSError("PRIVATE cleanup")
        original()

    def fail_after_start(**kwargs):
        original_start(**kwargs)
        raise OSError("PRIVATE startup failure")

    target.start = fail_after_start
    target.cleanup = retry
    result = acceptance.run_smoke(prepared, target_factory=lambda _: target)
    assert result["execution"] == "failed" and result["cleanup_confirmed"]
    assert result["cleanup_attempts"] == 2 and len(calls) == 2
    assert result["checks"] == {} and channel.retired
