"""Pinned PE coverage and real reader enforcement over synthetic image mappings."""
from dataclasses import replace
import hashlib
import struct

import pytest

from je_auto_control.utils.process_memory.image_guard import guard_probe_image
from je_auto_control.utils.process_memory.models import (
    FailureReason, MemoryObservationError, MemoryRegion, ModuleSpan, Observation,
    ProcessIdentity, ReadPlan, ReviewedProbe,
)
from je_auto_control.utils.process_memory.pe_image import plan_pinned_image
from je_auto_control.utils.process_memory.reader import ProcessMemoryReader
from je_auto_control.utils.process_memory.windows_launch import PinnedExecutable

OPTIONAL, TABLE = 152, 392
BASE = 0x100000
IDENTITY = ProcessIdentity("host", "session", 42, 100, "fixture", "1", "x64", 64)


def baseline():
    raw = bytearray(1536)
    raw[:2] = b"MZ"
    struct.pack_into("<I", raw, 60, 128)
    raw[128:132] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", raw, 132, 0x8664, 2, 0, 0, 0, 240, 0x22)
    struct.pack_into("<H", raw, OPTIONAL, 0x20B)
    for offset, value in ((16, 0x1000), (32, 0x1000), (36, 512), (56, 0x3000), (60, 512), (108, 16)):
        struct.pack_into("<I", raw, OPTIONAL + offset, value)
    struct.pack_into("<Q", raw, OPTIONAL + 24, 0x140000000)
    struct.pack_into("<II", raw, OPTIONAL + 112 + 5 * 8, 0x2000, 12)
    for offset, virtual, rva, size, pointer, flags in (
            (TABLE, 16, 0x1000, 512, 512, 0x60000020),
            (TABLE + 40, 512, 0x2000, 512, 1024, 0x40000040)):
        struct.pack_into("<IIII", raw, offset + 8, virtual, rva, size, pointer)
        struct.pack_into("<I", raw, offset + 36, flags)
    raw[512:528] = b"\x90" * 16
    struct.pack_into("<IIHH", raw, 1024, 0x2000, 12, 0, 0)
    return raw


def plan(raw):
    data = bytes(raw)
    return plan_pinned_image(data, PinnedExecutable("host", "session", "fixture", "1",
                                                   hashlib.sha256(data).hexdigest()))


def test_plan_covers_headers_and_entire_aligned_executable_range():
    raw = baseline()
    result = plan(raw)
    assert [(item.rva, item.size) for item in result.ranges] == [(0, 512), (0x1000, 4096)]
    assert result.ranges[1].sha256 == hashlib.sha256(bytes(raw[512:1024]) + bytes(3584)).hexdigest()
    assert result.checked_bytes == 4608 and result.image_size == 0x3000
    assert "\\x90" not in repr(result)


def test_additional_executable_section_cannot_be_omitted():
    raw = baseline()
    struct.pack_into("<I", raw, TABLE + 40 + 36, 0x60000020)
    assert [item.rva for item in plan(raw).ranges] == [0, 0x1000, 0x2000]


def test_baseline_hash_must_match_host_pin():
    raw = bytes(baseline())
    pin = PinnedExecutable("host", "session", "fixture", "1", "0" * 64)
    with pytest.raises(MemoryObservationError, match="unsupported"):
        plan_pinned_image(raw, pin)


@pytest.mark.parametrize("offset,value", [
    (TABLE + 36, 0xE0000020), (TABLE + 40 + 12, 0x1000), (TABLE + 40 + 20, 512),
    (TABLE + 20, 0xFFFFFF00), (TABLE + 8, 0x100001),
    (OPTIONAL + 16, 0x1010), (OPTIONAL + 56, 0x2000),
    (OPTIONAL + 60, 256), (OPTIONAL + 32, 0), (OPTIONAL + 108, 17),
    (OPTIONAL + 112 + 5 * 8 + 4, 13), (1024 + 4, 14), (1024 + 4, 7),
    (OPTIONAL + 112 + 12 * 8, 0x1000),
])
def test_invalid_layouts_are_refused(offset, value):
    raw = baseline()
    struct.pack_into("<I", raw, offset, value)
    with pytest.raises(MemoryObservationError):
        plan(raw)


@pytest.mark.parametrize("page,entry", [(0x1000, 0xA000), (0, 0xAFFC), (0x2000, 0x3000),
                                        (0x2000, 0xAFFC)])
def test_relocations_into_code_crossing_boundaries_or_unknown_types_are_refused(page, entry):
    raw = baseline()
    struct.pack_into("<I", raw, 1024, page)
    struct.pack_into("<H", raw, 1032, entry)
    with pytest.raises(MemoryObservationError):
        plan(raw)


@pytest.mark.parametrize("length", [0, 63, 128, 300, 471, 1025])
def test_truncated_images_are_refused_without_raw_exceptions(length):
    with pytest.raises(MemoryObservationError):
        plan(baseline()[:length])


class Provider:
    def __init__(self, raw, base=BASE):
        self.base = base
        self.memory = bytearray(0x3000)
        self.memory[:512] = raw[:512]
        struct.pack_into("<Q", self.memory, OPTIONAL + 24, base)  # the loader writes the real base here
        self.memory[0x1000:0x1200] = raw[512:1024]
        self.memory[0x2000:0x2200] = raw[1024:1536]
        struct.pack_into("<I", self.memory, 0x2100, 17)
        struct.pack_into("<Q", self.memory, 0x2110, 2)
        self.after_read = lambda: None
        self.closed = 0
        self.reads = []
        self.span = ModuleSpan(base, len(self.memory))

    def open_readonly(self, _identity):
        return self

    def identity(self):
        return IDENTITY

    def main_module(self):
        return self.span

    def query_region(self, _address):
        return MemoryRegion(self.base, len(self.memory), self.base, 4, True, True, False)

    def read(self, address, size):
        self.reads.append((address, size))
        offset = address - self.base
        result = bytes(self.memory[offset:offset + size])
        self.after_read()
        return result

    def close(self):
        self.closed += 1


def observed(provider, image_plan, *, checkpoint=lambda: None, **changes):
    reviewed = ReviewedProbe("fixture", "1", "fixture", ("1",), ("x64",), ("value",),
                             5000, 16, 1.0, 32,
                             lambda identity, view: ReadPlan(provider.base + 0x2100, 4, provider.base + 0x2110),
                             lambda raw, fields: {"value": int.from_bytes(raw, "little")})
    reviewed = replace(reviewed, **changes)
    return ProcessMemoryReader(provider).observe(IDENTITY, guard_probe_image(
        reviewed, image_plan, image_sha256=image_plan.image_sha256),
                                                 ("value",), target_id="fixture", checkpoint=checkpoint)


@pytest.mark.parametrize("base", [BASE, 0x50000000])
def test_real_reader_matches_pinned_ranges_after_rebasing(base):
    raw = baseline()
    provider = Provider(raw, base)
    result = observed(provider, plan(raw))
    assert isinstance(result, Observation) and dict(result.fields) == {"value": 17}
    assert result.bytes_read == 4628 and provider.closed == 1
    assert provider.reads[:2] == [(base, 512), (base + 0x1000, 4096)]


@pytest.mark.parametrize("value", [0x140000000, BASE + 0x10000, 0])
def test_a_loaded_image_base_other_than_the_measured_base_is_refused(value):
    raw = baseline()
    provider = Provider(raw)
    struct.pack_into("<Q", provider.memory, OPTIONAL + 24, value)
    result = observed(provider, plan(raw))
    assert result.reason is FailureReason.UNSUPPORTED
    assert len(provider.reads) == 1 and provider.closed == 1


def test_only_the_image_base_field_may_differ_from_the_file():
    raw = baseline()
    for offset in (OPTIONAL + 23, OPTIONAL + 32):
        provider = Provider(raw)
        provider.memory[offset] ^= 1
        assert observed(provider, plan(raw)).reason is FailureReason.UNSUPPORTED


def test_same_identity_and_file_with_changed_code_never_decodes_state():
    raw = baseline()
    provider = Provider(raw)
    provider.memory[0x1000] ^= 1
    result = observed(provider, plan(raw))
    assert result.reason is FailureReason.UNSUPPORTED
    assert len(provider.reads) == 2 and provider.closed == 1


def test_original_read_budget_is_not_expanded():
    raw = baseline()
    provider = Provider(raw)
    result = observed(provider, plan(raw), max_bytes=4609)
    assert result.reason is FailureReason.BUDGET_EXCEEDED and provider.closed == 1


def test_changed_module_fails_before_semantic_read():
    raw = baseline()
    provider = Provider(raw)
    provider.after_read = lambda: setattr(provider, "span", ModuleSpan(BASE, 0x2000))
    result = observed(provider, plan(raw))
    assert result.reason is FailureReason.UNSUPPORTED and provider.closed == 1
    assert len(provider.reads) == 2


def test_import_address_table_cannot_overlap_executable_bytes():
    raw = baseline()
    struct.pack_into("<II", raw, OPTIONAL + 112 + 12 * 8, 0x1000, 8)
    with pytest.raises(MemoryObservationError):
        plan(raw)


@pytest.mark.parametrize("offset", [100, 0x1800])
def test_header_and_executable_padding_are_checked(offset):
    raw = baseline()
    provider = Provider(raw)
    provider.memory[offset] ^= 1
    assert observed(provider, plan(raw)).reason is FailureReason.UNSUPPORTED


def test_cancelled_code_read_closes_handle_without_decoding():
    from je_auto_control.utils.exception.control_signals import OperationCancelledError
    raw = baseline()
    provider = Provider(raw)
    cancelled = False

    def cancel_after_read():
        nonlocal cancelled
        cancelled = True

    def checkpoint():
        if cancelled:
            raise OperationCancelledError("cancelled")

    provider.after_read = cancel_after_read
    with pytest.raises(OperationCancelledError):
        observed(provider, plan(raw), checkpoint=checkpoint)
    assert len(provider.reads) == 1 and provider.closed == 1


def test_plan_cannot_be_constructed_or_replaced_to_omit_coverage():
    from je_auto_control.utils.process_memory.pe_image import ImageCodePlan
    original = plan(baseline())
    with pytest.raises(MemoryObservationError):
        replace(original, ranges=())
    with pytest.raises(MemoryObservationError):
        ImageCodePlan("fixture", "1", original.image_sha256, original.image_size, original.ranges[:1],
                      original.base)


def test_equal_labels_cannot_bind_a_different_image_pin():
    raw = baseline()
    reviewed = ReviewedProbe("fixture", "1", "fixture", ("1",), ("x64",), ("value",),
                             5000, 16, 1.0, 32, lambda identity, view: ReadPlan(1, 4),
                             lambda data, fields: {"value": 1})
    with pytest.raises(MemoryObservationError):
        guard_probe_image(reviewed, plan(raw), image_sha256="0" * 64)
