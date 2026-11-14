"""Own fixed memory buffers and a bounded test-control pipe, without native inspection."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import struct
import sys
from typing import BinaryIO


PAYLOAD = struct.Struct("<I12s")
SEQUENCE = struct.Struct("<Q")
MAX_REQUEST_BYTES = 1024
STATES = frozenset({"ready", "busy", "done"})


class FixtureState:
    """Retain fixed buffers while publishing the fixture's expected semantic state."""

    def __init__(self) -> None:
        self.payload = ctypes.create_string_buffer(PAYLOAD.size)
        self.sequence = ctypes.create_string_buffer(SEQUENCE.size)
        self._generation = 0
        self._document_id = 17
        self._job_status = "ready"
        self._launch_nonce = secrets.token_hex(16)
        self.payload.raw = PAYLOAD.pack(self._document_id, b"ready")

    def bootstrap(self) -> dict[str, object]:
        """Describe self-reported locations, without asserting an OS-verified identity."""
        return {
            "kind": "bootstrap", "protocol_version": 1, "schema_version": 1,
            "identity": "self_reported", "pid": os.getpid(),
            "pointer_bits": ctypes.sizeof(ctypes.c_void_p) * 8,
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "launch_nonce": self._launch_nonce,
            "payload_address": ctypes.addressof(self.payload), "payload_size": PAYLOAD.size,
            "sequence_address": ctypes.addressof(self.sequence), "sequence_size": SEQUENCE.size,
        }

    def snapshot(self) -> dict[str, object]:
        """Return expected values independently of any cross-process memory reader."""
        return {"kind": "snapshot", "document_id": self._document_id,
                "job_status": self._job_status, "sequence": self._generation}

    def set_state(self, document_id: object, job_status: object) -> dict[str, object]:
        """Validate the complete change before publishing an odd/even sequence update."""
        if type(document_id) is not int or not 0 <= document_id <= 0xFFFFFFFF:
            return _error("invalid_state")
        if not isinstance(job_status, str) or job_status not in STATES:
            return _error("invalid_state")
        if self._generation > 0xFFFFFFFFFFFFFFFD:
            return _error("sequence_exhausted")
        encoded = PAYLOAD.pack(document_id, job_status.encode("ascii"))
        self.sequence.raw = SEQUENCE.pack(self._generation + 1)
        self.payload.raw = encoded
        self._document_id, self._job_status = document_id, job_status
        self._generation += 2
        self.sequence.raw = SEQUENCE.pack(self._generation)
        return self.snapshot()


def _error(code: str) -> dict[str, object]:
    return {"kind": "error", "code": code}


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _dispatch(state: FixtureState, request: object) -> dict[str, object]:
    if not isinstance(request, dict):
        return _error("invalid_request")
    command = request.get("command")
    if command == "snapshot" and set(request) == {"command"}:
        return state.snapshot()
    if command == "stop" and set(request) == {"command"}:
        return {"kind": "stopped"}
    if command == "set" and set(request) == {"command", "document_id", "job_status"}:
        return state.set_state(request["document_id"], request["job_status"])
    return _error("invalid_request")


def _emit(output: BinaryIO, record: dict[str, object]) -> None:
    output.write(json.dumps(record, separators=(",", ":")).encode("ascii") + b"\n")
    output.flush()


def serve(source: BinaryIO, output: BinaryIO) -> int:
    """Serve inherited pipes until stop, EOF or an oversized frame."""
    state = FixtureState()
    _emit(output, state.bootstrap())
    while True:
        line = source.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            return 0
        if len(line) > MAX_REQUEST_BYTES:
            _emit(output, _error("request_too_large"))
            return 2
        if not line.endswith(b"\n"):
            _emit(output, _error("incomplete_request"))
            return 2
        try:
            request = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object)
        except (ValueError, RecursionError):
            _emit(output, _error("invalid_json"))
            continue
        response = _dispatch(state, request)
        _emit(output, response)
        if response["kind"] == "stopped":
            return 0


if __name__ == "__main__":
    raise SystemExit(serve(sys.stdin.buffer, sys.stdout.buffer))
