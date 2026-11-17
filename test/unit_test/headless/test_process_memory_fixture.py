"""Check owned fixture buffers and hidden child control without native memory reads."""
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest


FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "process_memory_fixture.py"
SPEC = importlib.util.spec_from_file_location("process_memory_fixture", FIXTURE_PATH)
fixture_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture_module)


def _run_child(requests: bytes) -> tuple[int, list[dict], bytes]:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    child = subprocess.Popen(
        [sys.executable, "-I", "-u", str(FIXTURE_PATH)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=flags,
    )
    try:
        output, errors = child.communicate(requests, timeout=5)
        return child.returncode, [json.loads(line) for line in output.splitlines()], errors
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)


def test_buffers_have_exact_layout_and_retain_addresses_after_changes():
    state = fixture_module.FixtureState()
    payload_address = ctypes.addressof(state.payload)
    sequence_address = ctypes.addressof(state.sequence)
    assert state.payload.raw == struct.pack("<I12s", 17, b"ready")
    assert state.sequence.raw == bytes(8)
    for index, status in enumerate(("busy", "done", "ready"), start=1):
        result = state.set_state(0xFFFFFFFF, status)
        assert result == {"kind": "snapshot", "document_id": 0xFFFFFFFF,
                          "job_status": status, "sequence": index * 2}
        assert state.payload.raw == struct.pack("<I12s", 0xFFFFFFFF, status.encode("ascii"))
        assert state.sequence.raw == struct.pack("<Q", index * 2)
        assert ctypes.addressof(state.payload) == payload_address
        assert ctypes.addressof(state.sequence) == sequence_address


@pytest.mark.parametrize("document_id,status", [
    (True, "ready"), (-1, "ready"), (2**32, "ready"), (1.0, "ready"),
    ("1", "ready"), (1, "unknown"), (1, None), (1, ["ready"]),
])
def test_invalid_changes_leave_state_and_both_buffers_unchanged(document_id, status):
    state = fixture_module.FixtureState()
    expected = state.snapshot(), state.payload.raw, state.sequence.raw
    assert state.set_state(document_id, status) == {"kind": "error", "code": "invalid_state"}
    assert (state.snapshot(), state.payload.raw, state.sequence.raw) == expected


def test_sequence_exhaustion_leaves_state_and_buffers_unchanged():
    state = fixture_module.FixtureState()
    state._generation = 0xFFFFFFFFFFFFFFFE
    state.sequence.raw = struct.pack("<Q", state._generation)
    expected = state.snapshot(), state.payload.raw, state.sequence.raw
    assert state.set_state(42, "done") == {"kind": "error", "code": "sequence_exhausted"}
    assert (state.snapshot(), state.payload.raw, state.sequence.raw) == expected


def test_bootstrap_nonce_belongs_to_fixture_lifetime():
    state = fixture_module.FixtureState()
    first = state.bootstrap()
    state.set_state(42, "busy")
    assert state.bootstrap() == first


def test_child_accepts_maximum_frame_including_newline():
    command = b'{"command":"snapshot"}'
    frame = command + b" " * (fixture_module.MAX_REQUEST_BYTES - len(command) - 1) + b"\n"
    code, records, errors = _run_child(frame)
    assert code == 0
    assert errors == b""
    assert records[1:] == [{"kind": "snapshot", "document_id": 17, "job_status": "ready", "sequence": 0}]


def test_child_bootstrap_state_changes_and_stop():
    code, records, errors = _run_child(
        b'{"command":"snapshot"}\n'
        b'{"command":"set","document_id":42,"job_status":"busy"}\n'
        b'{"command":"snapshot"}\n'
        b'{"command":"stop"}\n'
        b'{"command":"set","document_id":1,"job_status":"done"}\n'
    )
    assert code == 0
    assert errors == b""
    bootstrap = records[0]
    assert bootstrap["kind"] == "bootstrap"
    assert bootstrap["identity"] == "self_reported"
    assert "birth" not in bootstrap
    assert bootstrap["protocol_version"] == bootstrap["schema_version"] == 1
    assert bootstrap["pid"] > 0
    assert bootstrap["pid"] != os.getpid()
    assert bootstrap["pointer_bits"] == struct.calcsize("P") * 8
    assert bootstrap["source_sha256"] == hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    assert bootstrap["payload_size"] == 16
    assert bootstrap["sequence_size"] == 8
    assert bootstrap["payload_address"] > 0
    assert bootstrap["sequence_address"] > 0
    assert records[1] == {"kind": "snapshot", "document_id": 17, "job_status": "ready", "sequence": 0}
    assert records[2] == records[3] == {
        "kind": "snapshot", "document_id": 42, "job_status": "busy", "sequence": 2,
    }
    assert records[4:] == [{"kind": "stopped"}]


@pytest.mark.parametrize("frame,reason", [
    (b'[]\n', "invalid_request"),
    (b'{"command":"read","address":1}\n', "invalid_request"),
    (b'{"command":"stop","extra":1}\n', "invalid_request"),
    (b'{"command":[]}\n', "invalid_request"),
    (b'{"command":"set","document_id":true,"job_status":"done"}\n', "invalid_state"),
    (b'{"command":"snapshot","command":"stop"}\n', "invalid_json"),
    (b'PRIVATE-MALFORMED-DATA\n', "invalid_json"),
    (b'\xff\n', "invalid_json"),
])
def test_child_rejects_bad_requests_without_mutation_or_echo(frame, reason):
    code, records, errors = _run_child(frame + b'{"command":"snapshot"}\n')
    assert code == 0
    assert errors == b""
    assert records[1] == {"kind": "error", "code": reason}
    assert records[2:] == [{"kind": "snapshot", "document_id": 17, "job_status": "ready", "sequence": 0}]


@pytest.mark.parametrize("frame,reason", [
    (b"x" * 1025, "request_too_large"),
    (b"x" * 1024 + b"\n", "request_too_large"),
    (b'{"command":"snapshot"}', "incomplete_request"),
])
def test_child_terminates_invalid_framing(frame, reason):
    code, records, errors = _run_child(frame)
    assert code == 2
    assert errors == b""
    assert records[1:] == [{"kind": "error", "code": reason}]


def test_clean_eof_and_fresh_launch_identity():
    first_code, first, first_errors = _run_child(b"")
    second_code, second, second_errors = _run_child(b"")
    assert first_code == second_code == 0
    assert first_errors == second_errors == b""
    assert len(first) == len(second) == 1
    assert first[0]["launch_nonce"] != second[0]["launch_nonce"]
    assert first[0]["source_sha256"] == second[0]["source_sha256"]


CHALLENGE = bytes(range(1, 17))


class _OwnBuffers:
    """A provider over this process's own fixture buffers: the reader's real code, no other process."""

    def __init__(self, state, identity):
        self._identity = identity
        self._buffers = [state.header, state.payload, state.sequence]
        self.reads = []

    def open_readonly(self, identity):
        return self

    def identity(self):
        return self._identity

    def query_region(self, address):
        from je_auto_control.utils.process_memory.models import MemoryRegion
        for buffer in self._buffers:
            base = ctypes.addressof(buffer)
            if base <= address < base + ctypes.sizeof(buffer):
                return MemoryRegion(base, ctypes.sizeof(buffer), base, 4, True, True, False)
        raise OSError("not a fixture buffer")

    def read(self, address, size):
        self.reads.append((address, size))
        return ctypes.string_at(address, size)

    def main_module(self):
        raise OSError("not used")

    def close(self):
        pass


def _observe_own(state, resolve, pid=None):
    from je_auto_control.utils.process_memory.models import ProcessIdentity, ReviewedProbe
    from je_auto_control.utils.process_memory.reader import ProcessMemoryReader
    identity = ProcessIdentity("host", "session", pid or os.getpid(), 1, "fixture", "1", "x64", 64)

    def decode(raw, fields):
        document_id, status = fixture_module.PAYLOAD.unpack(raw)
        values = {"document_id": document_id, "job_status": status.rstrip(b"\0").decode("ascii")}
        return {name: values[name] for name in fields}

    probe = ReviewedProbe("fixture", "1", "fixture", ("1",), ("x64",), ("document_id", "job_status"),
                          256, 8, 5.0, 32, resolve, decode)
    provider = _OwnBuffers(state, identity)
    result = ProcessMemoryReader(provider).observe(identity, probe, ("document_id", "job_status"), target_id="fixture")
    return result, provider


def test_the_header_records_the_challenge_and_where_the_buffers_are():
    state = fixture_module.FixtureState(CHALLENGE)
    magic, challenge, payload, sequence = fixture_module.HEADER.unpack(state.header.raw)
    assert (magic, challenge) == (b"JEPMFIX1", CHALLENGE)
    assert (payload, sequence) == (ctypes.addressof(state.payload), ctypes.addressof(state.sequence))
    bootstrap = state.bootstrap()
    assert (bootstrap["header_address"], bootstrap["header_size"]) == (ctypes.addressof(state.header), 40)


def test_a_header_that_reads_back_binds_the_bootstrap_locations():
    from je_auto_control.utils.process_memory.models import Observation
    state = fixture_module.FixtureState(CHALLENGE)
    state.set_state(23, "busy")
    resolve = fixture_module.challenge_resolver(CHALLENGE, state.bootstrap())
    result, provider = _observe_own(state, resolve)
    assert isinstance(result, Observation)
    assert result.consistency == "sequence_checked"
    assert result.fields == (("document_id", 23), ("job_status", "busy"))
    assert provider.reads[0] == (ctypes.addressof(state.header), 40)


@pytest.mark.parametrize("tamper", ["challenge", "magic", "payload_address", "pid"])
def test_a_header_that_does_not_match_the_launch_yields_no_plan(tamper):
    from je_auto_control.utils.process_memory.models import FailureReason
    state = fixture_module.FixtureState(CHALLENGE)
    bootstrap = state.bootstrap()
    challenge, pid = CHALLENGE, None
    if tamper == "challenge":
        challenge = bytes(range(2, 18))
    elif tamper == "magic":
        state.header.raw = b"NOTMAGIC" + state.header.raw[8:]
    elif tamper == "payload_address":
        bootstrap["payload_address"] += 1
    else:
        pid = os.getpid() + 1
    resolve = fixture_module.challenge_resolver(challenge, bootstrap)
    result, provider = _observe_own(state, resolve, pid)
    assert result.reason == FailureReason.UNSUPPORTED
    assert all(address == ctypes.addressof(state.header) for address, _size in provider.reads)


@pytest.mark.parametrize("challenge", [bytes(16), b"short", "0" * 16])
def test_an_unusable_challenge_is_refused_before_any_read(challenge):
    bootstrap = fixture_module.FixtureState().bootstrap()
    with pytest.raises(ValueError):
        fixture_module.challenge_resolver(challenge, bootstrap)


def test_the_child_writes_the_parents_challenge_into_its_own_header():
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    child = subprocess.run([sys.executable, "-I", "-u", str(FIXTURE_PATH), "--challenge", CHALLENGE.hex()],
                           input=b'{"command":"stop"}\n', capture_output=True, timeout=10, creationflags=flags)
    bootstrap = json.loads(child.stdout.splitlines()[0])
    assert child.returncode == 0
    assert bootstrap["header_size"] == 40
    assert type(bootstrap["header_address"]) is int
    refused = subprocess.run([sys.executable, "-I", "-u", str(FIXTURE_PATH), "--challenge", "zz"],
                             input=b"", capture_output=True, timeout=10, creationflags=flags)
    assert refused.returncode == 2
    assert refused.stdout == b""

def _change(state, **updates):
    return {"command": "compare_set", "operation_id": "operation-1",
            "launch_nonce": state.bootstrap()["launch_nonce"], "expected_sequence": 0,
            "document_id": 42, "job_status": "done", **updates}


def test_compare_set_replay_retains_receipt_after_intervening_change():
    state = fixture_module.FixtureState()
    request = _change(state)
    first = state.compare_set(request)
    assert first["kind"] == "receipt" and first["comparison"] == "atomic"
    assert first["sequence"] == 2
    first["sequence"] = 999
    state.set_state(99, "busy")
    replay = state.compare_set(request)
    assert replay["sequence"] == 2
    assert state.snapshot()["sequence"] == 4
    assert state.snapshot()["document_id"] == 99
    assert state.compare_set({**request, "document_id": 1})["code"] == "operation_conflict"


def test_refused_future_revision_never_becomes_an_effect_on_retry():
    state = fixture_module.FixtureState()
    request = _change(state, expected_sequence=2)
    assert state.compare_set(request)["code"] == "state_changed"
    state.set_state(18, "busy")
    assert state.compare_set(request)["code"] == "state_changed"
    assert state.snapshot()["sequence"] == 2
    assert state.snapshot()["document_id"] == 18


def test_operation_capacity_never_evicts_replay_protection():
    state = fixture_module.FixtureState()
    first = _change(state)
    for index in range(fixture_module.MAX_OPERATIONS):
        request = _change(state, operation_id=f"operation-{index}", expected_sequence=index * 2)
        assert state.compare_set(request)["kind"] == "receipt"
        if index == 0:
            first = request
    before = state.snapshot(), state.payload.raw, state.sequence.raw
    assert state.compare_set(_change(state, operation_id="new"))["code"] == "operation_limit"
    assert state.compare_set(first)["sequence"] == 2
    assert (state.snapshot(), state.payload.raw, state.sequence.raw) == before


@pytest.mark.parametrize("updates,reason", [
    ({"expected_sequence": True}, "invalid_request"),
    ({"expected_sequence": 1}, "invalid_request"),
    ({"expected_sequence": 2**64}, "invalid_request"),
    ({"operation_id": "x" * 129}, "invalid_request"),
    ({"operation_id": []}, "invalid_request"),
    ({"launch_nonce": "other-launch"}, "target_changed"),
    ({"document_id": True}, "invalid_state"),
    ({"job_status": []}, "invalid_state"),
    ({"address": 42}, "invalid_request"),
])
def test_compare_set_refusals_preserve_buffers(updates, reason):
    state = fixture_module.FixtureState()
    before = state.snapshot(), state.payload.raw, state.sequence.raw
    assert fixture_module._dispatch(state, _change(state, **updates))["code"] == reason
    assert (state.snapshot(), state.payload.raw, state.sequence.raw) == before


def test_restart_refuses_old_operation_and_launch_binding():
    original = fixture_module.FixtureState()
    request = _change(original)
    assert original.compare_set(request)["kind"] == "receipt"
    restarted = fixture_module.FixtureState()
    assert restarted.compare_set(request)["code"] == "target_changed"
    assert restarted.snapshot()["sequence"] == 0


def test_hidden_child_compare_set_replay_and_readback():
    from concurrent.futures import ThreadPoolExecutor
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    child = subprocess.Popen([sys.executable, "-I", "-u", str(FIXTURE_PATH)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=flags)
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            bootstrap = json.loads(pool.submit(child.stdout.readline).result(timeout=5))
            request = {"command": "compare_set", "operation_id": "ipc-1",
                       "launch_nonce": bootstrap["launch_nonce"], "expected_sequence": 0,
                       "document_id": 42, "job_status": "done"}
            wire = (json.dumps(request) + "\n").encode()
            output, errors = child.communicate(wire * 2 + b'{"command":"snapshot"}\n', timeout=5)
            records = [json.loads(line) for line in output.splitlines()]
            assert child.returncode == 0 and errors == b""
            assert records[0] == records[1]
            assert records[0]["kind"] == "receipt" and records[0]["sequence"] == 2
            assert records[2] == {"kind": "snapshot", "document_id": 42,
                                  "job_status": "done", "sequence": 2}
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)
