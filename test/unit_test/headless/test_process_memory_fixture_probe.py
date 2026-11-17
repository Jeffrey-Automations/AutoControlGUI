"""Exercise the reviewed fixture schema through the bounded semantic reader."""
from dataclasses import replace
import struct

import pytest

from je_auto_control.utils.process_memory.fixture_probe import FixtureBinding, decode_fixture
from je_auto_control.utils.process_memory.models import (
    FailureReason, MemoryObservationError, MemoryRegion, Observation, ProcessIdentity,
)
from je_auto_control.utils.process_memory.reader import ProcessMemoryReader


CHALLENGE = bytes(range(16))
IDENTITY = ProcessIdentity("host", "session", 42, 9, "pinned-fixture", "1", "x64", 64)


def bootstrap():
    return {"kind": "bootstrap", "protocol_version": 1, "schema_version": 1,
            "identity": "self_reported", "pid": 42, "pointer_bits": 64,
            "header_address": 4096, "header_size": 40, "payload_address": 8192,
            "payload_size": 16, "sequence_address": 9000, "sequence_size": 8}


class Provider:
    def __init__(self):
        self.chunks = {4096: struct.pack("<8s16sQQ", b"JEPMFIX1", CHALLENGE, 8192, 9000),
                       8192: struct.pack("<I12s", 17, b"ready"), 9000: bytes(8)}
        self.opens = self.closed = 0
        self.after_read = lambda address: None

    def open_readonly(self, identity):
        self.opens += 1
        return self

    def identity(self):
        return IDENTITY

    def query_region(self, address):
        return MemoryRegion(address, len(self.chunks[address]), address, 4, True, True, False)

    def read(self, address, size):
        value = self.chunks[address][:size]
        self.after_read(address)
        return value

    def close(self):
        self.closed += 1


def observe(provider, identity=IDENTITY, fields=("document_id", "job_status")):
    binding = FixtureBinding.from_bootstrap(CHALLENGE, bootstrap())
    return ProcessMemoryReader(provider).observe(identity, binding.probe("pinned-fixture"), fields,
                                                 target_id="fixture")


def test_reviewed_probe_reads_exact_values_with_one_shared_budget():
    provider = Provider()
    result = observe(provider)
    assert isinstance(result, Observation)
    assert result.fields == (("document_id", 17), ("job_status", "ready"))
    assert result.consistency == "sequence_checked"
    assert result.bytes_read == 72 and provider.closed == 1


@pytest.mark.parametrize("key,value", [
    ("protocol_version", 2), ("schema_version", True), ("payload_size", 17),
    ("sequence_size", 4), ("header_size", 39), ("pointer_bits", 16), ("pid", True),
    ("payload_address", 4100), ("header_address", -1), ("sequence_address", 2**64 - 7),
])
def test_invalid_bootstrap_is_rejected_without_reading(key, value):
    record = bootstrap()
    record[key] = value
    with pytest.raises(MemoryObservationError):
        FixtureBinding.from_bootstrap(CHALLENGE, record)


@pytest.mark.parametrize("raw", [b"", bytes(17), struct.pack("<I12s", 1, b"unknown"),
                                  struct.pack("<I12s", 1, b"ready\0x"),
                                  struct.pack("<I12s", 1, b"\xff")])
def test_invalid_payload_never_publishes_even_an_otherwise_valid_field(raw):
    provider = Provider()
    provider.chunks[8192] = raw.ljust(16, b"\0") if len(raw) < 16 else raw
    with pytest.raises(MemoryObservationError):
        decode_fixture(raw, ("document_id",))
    if len(raw) == 16:
        assert observe(provider, fields=("document_id",)).reason == FailureReason.DECODE_FAILED
        assert provider.closed == 1


def test_changed_version_and_unknown_fields_refuse_before_open():
    provider = Provider()
    assert observe(provider, replace(IDENTITY, version="2")).reason == FailureReason.UNSUPPORTED
    assert observe(provider, fields=("secret",)).reason == FailureReason.SCOPE_DENIED
    assert provider.opens == 0


def test_generation_change_rejects_mixed_state():
    provider = Provider()
    def advance(address):
        if address == 8192:
            provider.chunks[9000] = (2).to_bytes(8, "little")
    provider.after_read = advance
    assert observe(provider).reason == FailureReason.INCONSISTENT_SNAPSHOT
    assert provider.closed == 1


def test_bootstrap_copy_and_challenge_are_bound_to_each_launch():
    record = bootstrap()
    binding = FixtureBinding.from_bootstrap(CHALLENGE, record)
    record["payload_address"] = 9999
    provider = Provider()
    reader = ProcessMemoryReader(provider)
    result = reader.observe(IDENTITY, binding.probe("pinned-fixture"), ("job_status",), target_id="fixture")
    assert isinstance(result, Observation) and result.fields == (("job_status", "ready"),)
    provider.chunks[4096] = struct.pack("<8s16sQQ", b"JEPMFIX1", bytes(range(1, 17)), 8192, 9000)
    result = reader.observe(IDENTITY, binding.probe("pinned-fixture"), ("job_status",), target_id="fixture")
    assert result.reason == FailureReason.UNSUPPORTED
    assert provider.closed == 2


def test_x86_binding_accepts_last_valid_range_and_refuses_overflow():
    record = bootstrap() | {"pointer_bits": 32, "sequence_address": 2**32 - 8}
    binding = FixtureBinding.from_bootstrap(CHALLENGE, record)
    assert binding.pointer_bits == 32 and binding.sequence == 2**32 - 8
    record["sequence_address"] += 1
    with pytest.raises(MemoryObservationError):
        FixtureBinding.from_bootstrap(CHALLENGE, record)


def test_binding_refuses_mismatched_process_width_before_reading_header():
    binding = FixtureBinding.from_bootstrap(CHALLENGE, bootstrap())
    with pytest.raises(MemoryObservationError) as error:
        binding.resolve(replace(IDENTITY, architecture="x86", pointer_bits=32), None)
    assert error.value.reason == FailureReason.TARGET_CHANGED
