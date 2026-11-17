"""Typed process-image filename and read-only file acquisition calls."""
from __future__ import annotations

import ctypes
import sys
from typing import Callable, Protocol, cast

from .models import FailureReason, MemoryObservationError
from .windows_native import BOOL, PTR, U32, U64, NativeFunction, ProcessKernel, bind_process

I64 = ctypes.c_int64


class FileIdInfo(ctypes.Structure):
    """FILE_ID_INFO combines a volume serial number with a 128-bit file identity."""

    _fields_ = [("volume", U64), ("identifier", ctypes.c_ubyte * 16)]


class FileBasicInfo(ctypes.Structure):
    """FILE_BASIC_INFO timestamps and attributes, including native trailing alignment."""

    _fields_ = [("created", I64), ("accessed", I64), ("written", I64),
                ("changed", I64), ("attributes", U32)]


class ImageKernel(ProcessKernel, Protocol):
    """Native file reads and identity queries; no write, launch or memory-read calls."""

    QueryFullProcessImageNameW: NativeFunction
    CreateFileW: NativeFunction
    GetFileType: NativeFunction
    GetFileInformationByHandleEx: NativeFunction
    GetFileSizeEx: NativeFunction
    ReadFile: NativeFunction


def bind(kernel: ImageKernel) -> None:
    """Install explicit Unicode, fixed-width integer and pointer argument types."""
    bind_process(kernel)
    signatures: tuple[tuple[NativeFunction, list[object], object], ...] = (
        (kernel.QueryFullProcessImageNameW, [PTR, U32, ctypes.POINTER(ctypes.c_wchar), ctypes.POINTER(U32)], BOOL),
        (kernel.CreateFileW, [ctypes.c_wchar_p, U32, U32, PTR, U32, U32, PTR], PTR),
        (kernel.GetFileType, [PTR], U32),
        (kernel.GetFileInformationByHandleEx, [PTR, ctypes.c_int32, PTR, U32], BOOL),
        (kernel.GetFileSizeEx, [PTR, ctypes.POINTER(I64)], BOOL),
        (kernel.ReadFile, [PTR, PTR, U32, ctypes.POINTER(U32), PTR], BOOL),
    )
    for function, arguments, result in signatures:
        function.argtypes, function.restype = arguments, result


def load() -> tuple[ImageKernel, Callable[[], int]]:
    """Load private signatures only on explicit observer construction on Windows."""
    if sys.platform != "win32":
        raise MemoryObservationError(FailureReason.UNSUPPORTED)
    try:
        kernel = cast(ImageKernel, ctypes.WinDLL("kernel32", use_last_error=True))
        bind(kernel)
    except (OSError, AttributeError):
        raise MemoryObservationError(FailureReason.UNSUPPORTED) from None
    return kernel, ctypes.get_last_error
