"""Typed Win32 query/read bindings and caller-sized memory information layouts."""
from __future__ import annotations

import ctypes
import sys
from typing import Callable, Protocol, cast

from .models import FailureReason, MemoryObservationError

U16 = ctypes.c_uint16
U32 = ctypes.c_uint32
U64 = ctypes.c_uint64
PTR = ctypes.c_void_p
SIZE = ctypes.c_size_t
BOOL = ctypes.c_int32


class FileTime(ctypes.Structure):
    """Windows FILETIME has two DWORD fields on every caller architecture."""

    _fields_ = [("low", U32), ("high", U32)]


class MemoryInfo32(ctypes.Structure):
    """The 28-byte 32-bit MEMORY_BASIC_INFORMATION layout."""

    _fields_ = [("base", U32), ("allocation", U32), ("allocation_protection", U32),
                ("size", U32), ("state", U32), ("protection", U32), ("kind", U32)]


class MemoryInfo64(ctypes.Structure):
    """The 48-byte 64-bit layout, including both alignment fields."""

    _fields_ = [("base", U64), ("allocation", U64), ("allocation_protection", U32),
                ("alignment1", U32), ("size", U64), ("state", U32),
                ("protection", U32), ("kind", U32), ("alignment2", U32)]


class NativeFunction(Protocol):
    """A ctypes function with an explicitly installed native signature."""

    argtypes: list[object]
    restype: object

    def __call__(self, *arguments: object) -> int: ...


class Kernel(Protocol):
    """Only process identity, liveness, memory queries and handle release are exposed."""

    OpenProcess: NativeFunction
    CloseHandle: NativeFunction
    GetProcessId: NativeFunction
    GetProcessTimes: NativeFunction
    ProcessIdToSessionId: NativeFunction
    IsWow64Process2: NativeFunction
    WaitForSingleObject: NativeFunction
    VirtualQueryEx: NativeFunction
    ReadProcessMemory: NativeFunction


def bind(kernel: Kernel) -> None:
    """Install fixed-width DWORD/BOOL and pointer-sized address/length signatures."""
    signatures: tuple[tuple[NativeFunction, list[object], object], ...] = (
        (kernel.OpenProcess, [U32, BOOL, U32], PTR),
        (kernel.CloseHandle, [PTR], BOOL),
        (kernel.GetProcessId, [PTR], U32),
        (kernel.GetProcessTimes, [PTR, *[ctypes.POINTER(FileTime)] * 4], BOOL),
        (kernel.ProcessIdToSessionId, [U32, ctypes.POINTER(U32)], BOOL),
        (kernel.IsWow64Process2, [PTR, ctypes.POINTER(U16), ctypes.POINTER(U16)], BOOL),
        (kernel.WaitForSingleObject, [PTR, U32], U32),
        (kernel.VirtualQueryEx, [PTR, PTR, PTR, SIZE], SIZE),
        (kernel.ReadProcessMemory, [PTR, PTR, PTR, SIZE, ctypes.POINTER(SIZE)], BOOL),
    )
    for function, arguments, result in signatures:
        function.argtypes = arguments
        function.restype = result


def load() -> tuple[Kernel, Callable[[], int]]:
    """Load on explicit provider construction; imports never touch native resources."""
    if sys.platform != "win32":
        raise MemoryObservationError(FailureReason.UNSUPPORTED)
    try:
        kernel = cast(Kernel, ctypes.WinDLL("kernel32", use_last_error=True))
        bind(kernel)
    except (OSError, AttributeError):
        raise MemoryObservationError(FailureReason.UNSUPPORTED) from None
    return kernel, ctypes.get_last_error
