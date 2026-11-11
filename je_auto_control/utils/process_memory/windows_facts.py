"""Measure native birth, session and architecture through a retained process handle."""
from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from typing import Callable

from .models import FailureReason, MemoryObservationError
from .windows_native import FileTime, ProcessKernel, U16, U32

_ARCHITECTURES = {0x014C: ("x86", 32), 0x8664: ("x64", 64), 0xAA64: ("arm64", 64)}


@dataclass(frozen=True)
class NativeProcessFacts:
    """Measured retained-process facts for a host-reviewed application attestor."""

    pid: int = field(repr=False)
    birth: int = field(repr=False)
    session_id: int = field(repr=False)
    architecture: str
    pointer_bits: int


def _check(result: int, error: Callable[[], int], reason: FailureReason) -> None:
    if not result:
        raise MemoryObservationError(FailureReason.ACCESS_DENIED if error() == 5 else reason)


def _architecture(kernel: ProcessKernel, handle: int, error: Callable[[], int], bits: int) -> tuple[str, int]:
    process, native = U16(), U16()
    _check(kernel.IsWow64Process2(handle, ctypes.byref(process), ctypes.byref(native)), error,
           FailureReason.UNSUPPORTED)
    architecture = _ARCHITECTURES.get(process.value or native.value)
    if architecture is None or architecture[1] > bits:
        raise MemoryObservationError(FailureReason.UNSUPPORTED)
    return architecture


def measure_process(kernel: ProcessKernel, handle: int, error: Callable[[], int], bits: int) -> NativeProcessFacts:
    """Return actual native facts; a path, expected identity or bootstrap is never consulted."""
    if kernel.WaitForSingleObject(handle, 0) != 258:
        raise MemoryObservationError(FailureReason.TARGET_CHANGED)
    pid = kernel.GetProcessId(handle)
    times = [FileTime() for _ in range(4)]
    _check(pid, error, FailureReason.TARGET_CHANGED)
    _check(kernel.GetProcessTimes(handle, *[ctypes.byref(item) for item in times]), error,
           FailureReason.TARGET_CHANGED)
    session = U32()
    _check(kernel.ProcessIdToSessionId(pid, ctypes.byref(session)), error, FailureReason.TARGET_CHANGED)
    architecture = _architecture(kernel, handle, error, bits)
    birth = times[0].low | (times[0].high << 32)
    if not birth or kernel.WaitForSingleObject(handle, 0) != 258:
        raise MemoryObservationError(FailureReason.TARGET_CHANGED)
    return NativeProcessFacts(pid, birth, session.value, *architecture)
