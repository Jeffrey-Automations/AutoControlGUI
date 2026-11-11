"""Exercise injected Win32 calls and ownership without touching native process memory."""
import ctypes
from dataclasses import replace
import struct

import pytest

from je_auto_control.utils.process_memory.models import (
    FailureReason, MemoryObservationError, Observation, ObservationFailure,
    ProcessIdentity, ReadPlan, ReviewedProbe,
)
from je_auto_control.utils.process_memory.reader import ProcessMemoryReader
from je_auto_control.utils.process_memory.windows import WindowsProcessProvider
from je_auto_control.utils.process_memory.windows_native import FileTime, MemoryInfo32, MemoryInfo64, PTR, SIZE, U32


IDENTITY = ProcessIdentity("owned-host", "owned-session", 42, 0x100000002, "reviewed-image", "1", "x64", 64)


class Function:
    def __init__(self, implementation):
        self.implementation = implementation
        self.argtypes = []
        self.restype = None
        self.calls = []

    def __call__(self, *arguments):
        self.calls.append(arguments)
        return self.implementation(*arguments)


class Kernel:
    def __init__(self):
        self.pid, self.birth, self.session = IDENTITY.pid, IDENTITY.birth, 7
        self.machine, self.native = 0, 0x8664
        self.wait, self.error, self.close_ok, self.open_value = 258, 0, True, 91
        self.protection, self.state, self.query_short = 4, 0x1000, False
        self.read_ok, self.read_count = True, None
        self.after_read = lambda: None
        self.regions = [(0x1000, 8), (0x1008, 8)]
        self.payload = struct.pack("<I12s", 17, b"ready")
        for name, implementation in {
            "OpenProcess": lambda *args: self.open_value,
            "CloseHandle": lambda *args: self.close_ok,
            "GetProcessId": lambda *args: self.pid,
            "WaitForSingleObject": lambda *args: self.wait,
            "GetProcessTimes": self.times,
            "ProcessIdToSessionId": self.session_id,
            "IsWow64Process2": self.architecture,
            "VirtualQueryEx": self.query,
            "ReadProcessMemory": self.read,
        }.items():
            setattr(self, name, Function(implementation))

    def times(self, handle, birth, exit_time, kernel, user):
        birth._obj.low, birth._obj.high = self.birth & 0xFFFFFFFF, self.birth >> 32
        return True

    def session_id(self, pid, target):
        target._obj.value = self.session
        return True

    def architecture(self, handle, process, native):
        process._obj.value, native._obj.value = self.machine, self.native
        return True

    def query(self, handle, address, target, size):
        for base, length in self.regions:
            if base <= address < base + length:
                info = target._obj
                info.base, info.size, info.allocation = base, length, 0x1000
                info.protection, info.state = self.protection, self.state
                return size - 1 if self.query_short else size
        return 0

    def read(self, handle, address, buffer, size, count):
        buffer.raw = self.payload[address - 0x1000:address - 0x1000 + size]
        count._obj.value = size if self.read_count is None else self.read_count
        self.after_read()
        return self.read_ok


def attestor(facts):
    assert facts.session_id == 7
    return replace(IDENTITY, pid=facts.pid, birth=facts.birth,
                   architecture=facts.architecture, pointer_bits=facts.pointer_bits)


def provider(kernel, **options):
    return WindowsProcessProvider(attestor, kernel=kernel, last_error=lambda: kernel.error, **options)


def probe():
    return ReviewedProbe("fixture", "1", IDENTITY.executable, ("1",), ("x64", "x86"),
                         ("document_id",), 64, 8, 1, 32,
                         lambda identity: ReadPlan(0x1000, 16),
                         lambda raw, fields: {"document_id": struct.unpack("<I12s", raw)[0]})


def observe(kernel, **options):
    reader = ProcessMemoryReader(provider(kernel, **options))
    result = reader.observe(IDENTITY, probe(), ("document_id",), target_id="fixture")
    return reader, result


def test_win32_layout_and_signatures_are_fixed_width_and_pointer_safe():
    kernel = Kernel()
    provider(kernel)
    assert ctypes.sizeof(FileTime) == 8
    assert ctypes.sizeof(MemoryInfo32) == 28 and MemoryInfo32.size.offset == 12
    assert ctypes.sizeof(MemoryInfo64) == 48 and MemoryInfo64.size.offset == 24
    assert MemoryInfo64.protection.offset == 36
    assert kernel.OpenProcess.argtypes[0] is U32 and kernel.OpenProcess.restype is PTR
    assert kernel.VirtualQueryEx.restype is SIZE
    assert kernel.ReadProcessMemory.argtypes[3] is SIZE
    assert kernel.ReadProcessMemory.argtypes[4]._type_ is SIZE


def test_reader_reads_across_regions_and_releases_only_owned_query_handle():
    kernel = Kernel()
    reader, result = observe(kernel)
    assert isinstance(result, Observation)
    assert result.fields == (("document_id", 17),) and result.bytes_read == 16
    assert [call[3] for call in kernel.ReadProcessMemory.calls] == [8, 8]
    assert kernel.OpenProcess.calls == [(0x100410, False, 42)]
    assert kernel.CloseHandle.calls == [(91,)] and not reader.pending_cleanup


@pytest.mark.parametrize("caller,target_machine,native_machine,expected_bits,layout", [
    (64, 0, 0x8664, 64, MemoryInfo64),
    (64, 0x014C, 0x8664, 32, MemoryInfo64),
    (32, 0, 0x014C, 32, MemoryInfo32),
    (64, 0, 0xAA64, 64, MemoryInfo64),
    (64, 0x8664, 0xAA64, 64, MemoryInfo64),
])
def test_query_layout_uses_caller_width_not_target_width(caller, target_machine, native_machine, expected_bits, layout):
    kernel = Kernel()
    kernel.machine, kernel.native = target_machine, native_machine
    expected = replace(IDENTITY, architecture="x86", pointer_bits=32) if expected_bits == 32 else IDENTITY
    handle = provider(kernel, caller_bits=caller).open_readonly(expected)
    try:
        assert handle.identity().pointer_bits == expected_bits
        assert handle.query_region(0x1000).size == 8
        assert isinstance(kernel.VirtualQueryEx.calls[-1][2]._obj, layout)
    finally:
        handle.close()


def test_32_bit_caller_rejects_64_bit_target_before_open():
    kernel = Kernel()
    with pytest.raises(MemoryObservationError, match="unsupported"):
        provider(kernel, caller_bits=32).open_readonly(IDENTITY)
    assert not kernel.OpenProcess.calls


@pytest.mark.parametrize("protection,state", [(0x104, 0x1000), (1, 0x1000), (0x10, 0x1000),
                                              (4, 0x2000), (4, 0x10000)])
def test_reader_refuses_guard_unreadable_and_uncommitted_regions(protection, state):
    kernel = Kernel()
    kernel.protection, kernel.state = protection, state
    _, result = observe(kernel)
    assert result == ObservationFailure(FailureReason.UNREADABLE_REGION)
    assert not kernel.ReadProcessMemory.calls and kernel.CloseHandle.calls == [(91,)]


@pytest.mark.parametrize("read_ok,count,error,reason", [
    (True, 7, 0, FailureReason.PARTIAL_READ),
    (False, 0, 299, FailureReason.PARTIAL_READ),
    (False, 0, 5, FailureReason.ACCESS_DENIED),
    (False, 0, 998, FailureReason.UNREADABLE_REGION),
])
def test_failed_or_short_reads_never_publish_partial_values(read_ok, count, error, reason):
    kernel = Kernel()
    kernel.read_ok, kernel.read_count, kernel.error = read_ok, count, error
    _, result = observe(kernel)
    assert result == ObservationFailure(reason)
    assert kernel.CloseHandle.calls == [(91,)]


@pytest.mark.parametrize("attribute,value", [("pid", 43), ("birth", IDENTITY.birth + 1),
                                           ("wait", 0), ("wait", 0xFFFFFFFF)])
def test_reused_or_exited_target_is_rejected_before_memory_read(attribute, value):
    kernel = Kernel()
    setattr(kernel, attribute, value)
    _, result = observe(kernel)
    assert result == ObservationFailure(FailureReason.TARGET_CHANGED)
    assert not kernel.ReadProcessMemory.calls and kernel.CloseHandle.calls == [(91,)]


@pytest.mark.parametrize("attribute,value", [("birth", IDENTITY.birth + 1), ("wait", 0), ("protection", 2)])
def test_changed_target_or_region_during_read_discards_bytes(attribute, value):
    kernel = Kernel()
    kernel.after_read = lambda: setattr(kernel, attribute, value)
    _, result = observe(kernel)
    assert result == ObservationFailure(FailureReason.TARGET_CHANGED)
    assert kernel.CloseHandle.calls == [(91,)]


def test_open_access_denied_does_not_invent_handle_cleanup():
    kernel = Kernel()
    kernel.open_value, kernel.error = 0, 5
    _, result = observe(kernel)
    assert result == ObservationFailure(FailureReason.ACCESS_DENIED)
    assert not kernel.CloseHandle.calls


def test_failed_close_remains_owned_until_reader_retry():
    kernel = Kernel()
    kernel.close_ok = False
    reader, result = observe(kernel)
    assert result == ObservationFailure(FailureReason.CLEANUP_FAILED, retired=False)
    assert reader.pending_cleanup
    kernel.close_ok = True
    assert reader.close_pending() and not reader.pending_cleanup
    assert kernel.CloseHandle.calls == [(91,), (91,)]


def test_attestor_cannot_replace_measured_birth():
    kernel = Kernel()
    native = WindowsProcessProvider(lambda facts: replace(IDENTITY, birth=1), kernel=kernel,
                                    last_error=lambda: 0)
    reader = ProcessMemoryReader(native)
    result = reader.observe(IDENTITY, probe(), ("document_id",), target_id="fixture")
    assert result == ObservationFailure(FailureReason.TARGET_CHANGED)
    assert not kernel.ReadProcessMemory.calls and kernel.CloseHandle.calls == [(91,)]


def test_unknown_architecture_and_short_query_are_not_accepted():
    kernel = Kernel()
    kernel.machine = 0x9999
    _, result = observe(kernel)
    assert result == ObservationFailure(FailureReason.UNSUPPORTED)
    kernel = Kernel()
    kernel.query_short = True
    _, result = observe(kernel)
    assert result == ObservationFailure(FailureReason.UNREADABLE_REGION)


@pytest.mark.parametrize("address,size,reason", [(-1, 1, "unreadable_region"), (1 << 64, 1, "unreadable_region"),
                                             (0x1000, 0, "unreadable_region"), (0x1000, True, "unreadable_region"),
                                             (0x1000, (1 << 20) + 1, "budget_exceeded"),
                                             (0x1000, 16, "unreadable_region")])
def test_direct_handle_read_has_its_own_bounds(address, size, reason):
    kernel = Kernel()
    handle = provider(kernel).open_readonly(IDENTITY)
    try:
        with pytest.raises(MemoryObservationError, match=reason):
            handle.read(address, size)
        assert not kernel.ReadProcessMemory.calls
    finally:
        handle.close()


def test_closed_handle_cannot_be_reused_and_close_is_idempotent():
    kernel = Kernel()
    handle = provider(kernel).open_readonly(IDENTITY)
    handle.close()
    handle.close()
    with pytest.raises(MemoryObservationError, match="target_changed"):
        handle.identity()
    assert kernel.CloseHandle.calls == [(91,)]


def test_process_exit_during_failed_native_read_is_distinguished_from_partial_read():
    kernel = Kernel()
    kernel.read_ok, kernel.error = False, 299
    kernel.after_read = lambda: setattr(kernel, "wait", 0)
    _, result = observe(kernel)
    assert result == ObservationFailure(FailureReason.TARGET_CHANGED)
    assert kernel.CloseHandle.calls == [(91,)]


def test_cancel_after_native_read_propagates_after_handle_close():
    from concurrent.futures import CancelledError

    kernel = Kernel()
    cancelled = False

    def checkpoint():
        if cancelled:
            raise CancelledError()

    def cancel():
        nonlocal cancelled
        cancelled = True

    kernel.after_read = cancel
    reader = ProcessMemoryReader(provider(kernel))
    with pytest.raises(CancelledError):
        reader.observe(IDENTITY, probe(), ("document_id",), target_id="fixture", checkpoint=checkpoint)
    assert kernel.CloseHandle.calls == [(91,)] and not reader.pending_cleanup


def test_cancel_before_open_does_not_acquire_native_handle():
    from concurrent.futures import CancelledError

    kernel = Kernel()

    def checkpoint():
        raise CancelledError()

    reader = ProcessMemoryReader(provider(kernel))
    with pytest.raises(CancelledError):
        reader.observe(IDENTITY, probe(), ("document_id",), target_id="fixture", checkpoint=checkpoint)
    assert not kernel.OpenProcess.calls and not kernel.CloseHandle.calls
