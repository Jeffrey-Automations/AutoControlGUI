"""Owned Windows read handles with measured native facts and reviewed application attestation."""
from __future__ import annotations

import ctypes
import threading
from typing import Callable, NoReturn

from .models import FailureReason, MemoryObservationError, MemoryRegion, ProcessIdentity
from .windows_native import Kernel, MemoryInfo32, MemoryInfo64, SIZE, bind, load
from .windows_facts import NativeProcessFacts as NativeProcessFacts, measure_process

_ACCESS = 0x00100000 | 0x0400 | 0x0010
_READABLE = frozenset({0x02, 0x04, 0x08, 0x20, 0x40, 0x80})
_MAX_READ = 1 << 20


Attestor = Callable[[NativeProcessFacts], ProcessIdentity]


def _fail(reason: FailureReason) -> NoReturn:
    raise MemoryObservationError(reason)


def _range(address: int, size: int, bits: int) -> None:
    if (type(address) is not int or type(size) is not int or address < 0 or size <= 0
            or address >= 1 << bits or size > (1 << bits) - address):
        _fail(FailureReason.UNREADABLE_REGION)


class WindowsProcessHandle:
    """Serialize read/query/close; an unsuccessful close keeps its native handle owned."""

    def __init__(self, kernel: Kernel, attestor: Attestor,
                 last_error: Callable[[], int], caller_bits: int) -> None:
        self._kernel = kernel
        self._handle: int | None = None
        self._attestor = attestor
        self._last_error = last_error
        self._caller_bits = caller_bits
        self._lock = threading.RLock()

    def _owned(self) -> int:
        if self._handle is None:
            _fail(FailureReason.TARGET_CHANGED)
        return self._handle

    def _error(self, fallback: FailureReason) -> NoReturn:
        code = self._last_error()
        _fail(FailureReason.ACCESS_DENIED if code == 5 else fallback)

    def _alive(self, handle: int) -> None:
        if self._kernel.WaitForSingleObject(handle, 0) != 258:
            _fail(FailureReason.TARGET_CHANGED)

    def _facts(self) -> NativeProcessFacts:
        return measure_process(self._kernel, self._owned(), self._last_error, self._caller_bits)

    def identity(self) -> ProcessIdentity:
        """Measure native facts, then ask the reviewed owner to attest application identity."""
        with self._lock:
            before = self._facts()
            identity = self._attestor(before)
            if not isinstance(identity, ProcessIdentity):
                _fail(FailureReason.UNSUPPORTED)
            if ((identity.pid, identity.birth, identity.architecture, identity.pointer_bits)
                    != (before.pid, before.birth, before.architecture, before.pointer_bits)
                    or self._facts() != before):
                _fail(FailureReason.TARGET_CHANGED)
            return identity

    def _region(self, address: int, bits: int) -> MemoryRegion:
        _range(address, 1, bits)
        info = MemoryInfo64() if self._caller_bits == 64 else MemoryInfo32()
        size = ctypes.sizeof(info)
        returned = self._kernel.VirtualQueryEx(self._owned(), address, ctypes.byref(info), size)
        if not returned:
            self._error(FailureReason.UNREADABLE_REGION)
        if returned != size:
            _fail(FailureReason.UNREADABLE_REGION)
        _range(info.base, info.size, bits)
        if not info.base <= address < info.base + info.size:
            _fail(FailureReason.UNREADABLE_REGION)
        committed = info.state == 0x1000
        protection = info.protection if committed else 0
        allocation = info.allocation if info.state != 0x10000 else 0
        return MemoryRegion(info.base, info.size, allocation, protection, committed,
                            committed and (protection & 0xFF) in _READABLE, bool(protection & 0x100))

    def query_region(self, address: int) -> MemoryRegion:
        """Query the intersecting region using the caller ABI, even for a WOW64 target."""
        with self._lock:
            facts = self._facts()
            region = self._region(address, facts.pointer_bits)
            if self._facts() != facts:
                _fail(FailureReason.TARGET_CHANGED)
            return region

    def _read_chunk(self, address: int, size: int) -> bytes:
        buffer, count = ctypes.create_string_buffer(size), SIZE()
        if not self._kernel.ReadProcessMemory(self._owned(), address, buffer, size, ctypes.byref(count)):
            code = self._last_error()
            self._alive(self._owned())
            reason = FailureReason.PARTIAL_READ if code == 299 else FailureReason.UNREADABLE_REGION
            _fail(FailureReason.ACCESS_DENIED if code == 5 else reason)
        if count.value != size:
            _fail(FailureReason.PARTIAL_READ)
        return buffer.raw

    def read(self, address: int, size: int) -> bytes:
        """Read one bounded committed readable region; never return partial bytes."""
        with self._lock:
            facts = self._facts()
            _range(address, size, facts.pointer_bits)
            if size > _MAX_READ:
                _fail(FailureReason.BUDGET_EXCEEDED)
            region = self._region(address, facts.pointer_bits)
            if (not region.committed or not region.readable or region.guard
                    or size > region.base + region.size - address):
                _fail(FailureReason.UNREADABLE_REGION)
            raw = self._read_chunk(address, size)
            if self._facts() != facts or self._region(address, facts.pointer_bits) != region:
                _fail(FailureReason.TARGET_CHANGED)
            return raw

    def close(self) -> None:
        """Retain ownership on failure; successful repeated closes are harmless."""
        with self._lock:
            if self._handle is not None:
                if not self._kernel.CloseHandle(self._handle):
                    _fail(FailureReason.CLEANUP_FAILED)
                self._handle = None


class WindowsProcessProvider:
    """Open query/read handles; application identity requires an explicit reviewed attestor."""

    def __init__(self, attestor: Attestor, *, kernel: Kernel | None = None,
                 last_error: Callable[[], int] | None = None, caller_bits: int | None = None) -> None:
        bits = ctypes.sizeof(ctypes.c_void_p) * 8 if caller_bits is None else caller_bits
        if type(bits) is not int or bits not in (32, 64) or not callable(attestor):
            _fail(FailureReason.UNSUPPORTED)
        if kernel is None:
            if bits != ctypes.sizeof(ctypes.c_void_p) * 8:
                _fail(FailureReason.UNSUPPORTED)
            kernel, last_error = load()
        else:
            if last_error is None:
                _fail(FailureReason.UNSUPPORTED)
            bind(kernel)
        self._kernel, self._last_error = kernel, last_error
        self._attestor, self._caller_bits = attestor, bits

    def open_readonly(self, identity: ProcessIdentity) -> WindowsProcessHandle:
        """Transfer ownership immediately; all fallible identity work happens on the returned handle."""
        if identity.pointer_bits > self._caller_bits:
            _fail(FailureReason.UNSUPPORTED)
        owned = WindowsProcessHandle(self._kernel, self._attestor, self._last_error, self._caller_bits)
        handle = self._kernel.OpenProcess(_ACCESS, False, identity.pid)
        if not handle:
            _fail(FailureReason.ACCESS_DENIED if self._last_error() == 5 else FailureReason.TARGET_CHANGED)
        owned._handle = handle
        return owned
