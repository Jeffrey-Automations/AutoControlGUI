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
    before = state.snapshot(), state.payload.raw, state.sequence.raw
    assert state.set_state(document_id, status) == {"kind": "error", "code": "invalid_state"}
    assert (state.snapshot(), state.payload.raw, state.sequence.raw) == before


def test_sequence_exhaustion_leaves_state_and_buffers_unchanged():
    state = fixture_module.FixtureState()
    state._generation = 0xFFFFFFFFFFFFFFFE
    state.sequence.raw = struct.pack("<Q", state._generation)
    before = state.snapshot(), state.payload.raw, state.sequence.raw
    assert state.set_state(42, "done") == {"kind": "error", "code": "sequence_exhausted"}
    assert (state.snapshot(), state.payload.raw, state.sequence.raw) == before


def test_bootstrap_nonce_belongs_to_fixture_lifetime():
    state = fixture_module.FixtureState()
    first = state.bootstrap()
    state.set_state(42, "busy")
    assert state.bootstrap() == first


def test_child_accepts_maximum_frame_including_newline():
    command = b'{"command":"snapshot"}'
    frame = command + b" " * (fixture_module.MAX_REQUEST_BYTES - len(command) - 1) + b"\n"
    code, records, errors = _run_child(frame)
    assert code == 0 and errors == b""
    assert records[1:] == [{"kind": "snapshot", "document_id": 17, "job_status": "ready", "sequence": 0}]


def test_child_bootstrap_state_changes_and_stop():
    code, records, errors = _run_child(
        b'{"command":"snapshot"}\n'
        b'{"command":"set","document_id":42,"job_status":"busy"}\n'
        b'{"command":"snapshot"}\n'
        b'{"command":"stop"}\n'
        b'{"command":"set","document_id":1,"job_status":"done"}\n'
    )
    assert code == 0 and errors == b""
    bootstrap = records[0]
    assert bootstrap["kind"] == "bootstrap"
    assert bootstrap["identity"] == "self_reported" and "birth" not in bootstrap
    assert bootstrap["protocol_version"] == bootstrap["schema_version"] == 1
    assert bootstrap["pid"] > 0 and bootstrap["pid"] != os.getpid()
    assert bootstrap["pointer_bits"] == struct.calcsize("P") * 8
    assert bootstrap["source_sha256"] == hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    assert bootstrap["payload_size"] == 16 and bootstrap["sequence_size"] == 8
    assert bootstrap["payload_address"] > 0 and bootstrap["sequence_address"] > 0
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
    assert code == 0 and errors == b""
    assert records[1] == {"kind": "error", "code": reason}
    assert records[2:] == [{"kind": "snapshot", "document_id": 17, "job_status": "ready", "sequence": 0}]


@pytest.mark.parametrize("frame,reason", [
    (b"x" * 1025, "request_too_large"),
    (b"x" * 1024 + b"\n", "request_too_large"),
    (b'{"command":"snapshot"}', "incomplete_request"),
])
def test_child_terminates_invalid_framing(frame, reason):
    code, records, errors = _run_child(frame)
    assert code == 2 and errors == b""
    assert records[1:] == [{"kind": "error", "code": reason}]


def test_clean_eof_and_fresh_launch_identity():
    first_code, first, first_errors = _run_child(b"")
    second_code, second, second_errors = _run_child(b"")
    assert first_code == second_code == 0 and first_errors == second_errors == b""
    assert len(first) == len(second) == 1
    assert first[0]["launch_nonce"] != second[0]["launch_nonce"]
    assert first[0]["source_sha256"] == second[0]["source_sha256"]
