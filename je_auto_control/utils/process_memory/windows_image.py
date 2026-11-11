"""Observe an image file while retaining its process and deny-write/delete file leases."""
from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import math
import threading
import time
from typing import Callable, NoReturn, TypeVar

from .models import FailureReason, MemoryObservationError
from .windows_facts import NativeProcessFacts, measure_process
from .windows_image_native import FileBasicInfo, FileIdInfo, I64, ImageKernel, bind, load
from .windows_native import U32

_QUERY_ACCESS = 0x00100000 | 0x1000
_PATH_CHARACTERS = 32768
_CHUNK_BYTES = 65536
_MAX_IMAGE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class ObservedImageFile:
    """Measured current image-file evidence, never proof of loaded code or a launch."""

    process: NativeProcessFacts = field(repr=False)
    volume: int = field(repr=False)
    file_id: bytes = field(repr=False)
    size: int
    sha256: str = field(repr=False)


@dataclass(frozen=True)
class _FileFacts:
    volume: int
    file_id: bytes
    size: int
    created: int
    written: int
    changed: int
    attributes: int


class _State(Enum):
    NEW = "new"
    ACTIVE = "active"
    RETIRED = "retired"


_Result = TypeVar("_Result")


def _native(call: Callable[[], _Result], reason: FailureReason) -> _Result:
    try:
        return call()
    except MemoryObservationError:
        raise
    except Exception as error:  # reason: ABI/provider errors must not expose filenames, handles or addresses
        denied = isinstance(error, OSError) and getattr(error, "winerror", None) == 5
        raise MemoryObservationError(FailureReason.ACCESS_DENIED if denied else reason) from None


def _fail(reason: FailureReason) -> NoReturn:
    raise MemoryObservationError(reason)


def _bounds(pid: int, max_bytes: int, timeout: float) -> None:
    if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
        _fail(FailureReason.UNSUPPORTED)
    if type(max_bytes) is not int or not 0 < max_bytes <= _MAX_IMAGE_BYTES:
        _fail(FailureReason.BUDGET_EXCEEDED)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        _fail(FailureReason.DEADLINE_EXCEEDED)


class WindowsImageObserver:
    """One acquisition owner; successful evidence keeps leases until explicit close.

    Failures and cancellation retire the owner and attempt all cleanup. Failed
    closes remain owned for another close call. This object cannot be reused for
    another process. Callers must retain it while pending_cleanup is true.
    """

    def __init__(self, *, kernel: ImageKernel | None = None,
                 last_error: Callable[[], int] | None = None,
                 caller_bits: int | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        bits = ctypes.sizeof(ctypes.c_void_p) * 8 if caller_bits is None else caller_bits
        if type(bits) is not int or bits not in (32, 64):
            _fail(FailureReason.UNSUPPORTED)
        if kernel is None:
            if bits != ctypes.sizeof(ctypes.c_void_p) * 8:
                _fail(FailureReason.UNSUPPORTED)
            kernel, last_error = load()
        else:
            if last_error is None:
                _fail(FailureReason.UNSUPPORTED)
            bind(kernel)
        self._kernel, self._error, self._bits, self._clock = kernel, last_error, bits, clock
        self._state = _State.NEW
        self._handles: list[int] = []
        self._lock = threading.RLock()

    @property
    def pending_cleanup(self) -> bool:
        """Whether retirement left any failed handle owned for explicit retry."""
        with self._lock:
            return self._state is _State.RETIRED and bool(self._handles)

    def _check(self, deadline: float, checkpoint: Callable[[], None]) -> None:
        checkpoint()
        if self._state is not _State.ACTIVE:
            _fail(FailureReason.TARGET_CHANGED)
        now = self._clock()
        if not math.isfinite(deadline) or not math.isfinite(now) or now >= deadline:
            _fail(FailureReason.DEADLINE_EXCEEDED)

    def _require(self, result: int, reason: FailureReason) -> None:
        if not result:
            _fail(FailureReason.ACCESS_DENIED if _native(self._error, reason) == 5 else reason)

    def _process(self, pid: int) -> int:
        handle = _native(lambda: self._kernel.OpenProcess(_QUERY_ACCESS, False, pid), FailureReason.TARGET_CHANGED)
        self._require(handle, FailureReason.TARGET_CHANGED)
        self._handles.append(handle)
        return handle

    def _path(self, process: int) -> str:
        buffer, length = ctypes.create_unicode_buffer(_PATH_CHARACTERS), U32(_PATH_CHARACTERS)
        self._require(_native(lambda: self._kernel.QueryFullProcessImageNameW(
            process, 0, buffer, ctypes.byref(length)), FailureReason.UNSUPPORTED), FailureReason.UNSUPPORTED)
        if not 0 < length.value < _PATH_CHARACTERS:
            _fail(FailureReason.UNSUPPORTED)
        value = buffer.value
        if len(value.encode("utf-16-le", "surrogatepass")) // 2 != length.value or buffer[length.value] != "\0":
            _fail(FailureReason.UNSUPPORTED)
        return value

    def _file(self, path: str) -> int:
        handle = _native(lambda: self._kernel.CreateFileW(path, 0x80000000, 1, None, 3, 0, None),
                         FailureReason.UNSUPPORTED)
        if not handle or handle in (-1, (1 << self._bits) - 1):
            code = _native(self._error, FailureReason.UNSUPPORTED)
            _fail(FailureReason.ACCESS_DENIED if code == 5 else FailureReason.UNSUPPORTED)
        self._handles.append(handle)
        if _native(lambda: self._kernel.GetFileType(handle), FailureReason.UNSUPPORTED) != 1:
            _fail(FailureReason.UNSUPPORTED)
        return handle

    def _file_facts(self, handle: int) -> _FileFacts:
        identity, basic, size = FileIdInfo(), FileBasicInfo(), I64()
        self._require(_native(lambda: self._kernel.GetFileInformationByHandleEx(
            handle, 18, ctypes.byref(identity), ctypes.sizeof(identity)), FailureReason.UNSUPPORTED),
            FailureReason.UNSUPPORTED)
        self._require(_native(lambda: self._kernel.GetFileInformationByHandleEx(
            handle, 0, ctypes.byref(basic), ctypes.sizeof(basic)), FailureReason.UNSUPPORTED),
            FailureReason.UNSUPPORTED)
        self._require(_native(lambda: self._kernel.GetFileSizeEx(handle, ctypes.byref(size)),
                              FailureReason.UNSUPPORTED), FailureReason.UNSUPPORTED)
        if size.value <= 0 or basic.attributes & 0x10:
            _fail(FailureReason.UNSUPPORTED)
        return _FileFacts(identity.volume, bytes(identity.identifier), size.value,
                          basic.created, basic.written, basic.changed, basic.attributes)

    def _read(self, handle: int, size: int) -> bytes:
        buffer, count = ctypes.create_string_buffer(size), U32()
        self._require(_native(lambda: self._kernel.ReadFile(handle, buffer, size, ctypes.byref(count), None),
                              FailureReason.PARTIAL_READ), FailureReason.PARTIAL_READ)
        if count.value != size:
            _fail(FailureReason.PARTIAL_READ)
        return buffer.raw

    def _facts(self, process: int) -> NativeProcessFacts:
        return _native(lambda: measure_process(self._kernel, process, self._error, self._bits),
                       FailureReason.TARGET_CHANGED)

    def _unchanged(self, process: int, image: int, path: str,
                   facts: NativeProcessFacts, file: _FileFacts) -> None:
        actual = self._facts(process)
        if actual != facts or self._path(process) != path or self._file_facts(image) != file:
            _fail(FailureReason.TARGET_CHANGED)

    def _measure(self, pid: int, max_bytes: int, deadline: float,
                 checkpoint: Callable[[], None]) -> ObservedImageFile:
        self._check(deadline, checkpoint)
        process = self._process(pid)
        self._check(deadline, checkpoint)
        facts = self._facts(process)
        if facts.pid != pid:
            _fail(FailureReason.TARGET_CHANGED)
        path = self._path(process)
        self._check(deadline, checkpoint)
        image = self._file(path)
        self._check(deadline, checkpoint)
        file = self._file_facts(image)
        if file.size > max_bytes:
            _fail(FailureReason.BUDGET_EXCEEDED)
        digest, remaining = hashlib.sha256(), file.size
        self._unchanged(process, image, path, facts, file)
        while remaining:
            self._check(deadline, checkpoint)
            size = min(remaining, _CHUNK_BYTES)
            digest.update(self._read(image, size))
            self._check(deadline, checkpoint)
            self._unchanged(process, image, path, facts, file)
            remaining -= size
        self._check(deadline, checkpoint)
        return ObservedImageFile(facts, file.volume, file.file_id, file.size, digest.hexdigest())

    def observe(self, pid: int, *, max_bytes: int, timeout: float,
                checkpoint: Callable[[], None]) -> ObservedImageFile:
        """Measure one current image file under finite caller bounds; retain successful leases.

        Checkpoints detect cancellation/revocation and deadline overruns between
        acquisition phases and file chunks, not every individual native call.
        They cannot interrupt a blocked OS call. No attestation is
        issued, even if a caller recognizes the measured digest.
        """
        with self._lock:
            if self._state is not _State.NEW:
                _fail(FailureReason.TARGET_CHANGED)
            _bounds(pid, max_bytes, timeout)
            self._state = _State.ACTIVE
            try:
                return self._measure(pid, max_bytes, self._clock() + timeout, checkpoint)
            except BaseException:
                try:
                    self.close()
                except MemoryObservationError:
                    pass
                raise

    def close(self) -> None:
        """Retire permanently, trying every owned handle and retaining failed closes."""
        with self._lock:
            self._state = _State.RETIRED
            for handle in tuple(reversed(self._handles)):
                try:
                    closed = _native(lambda: self._kernel.CloseHandle(handle), FailureReason.CLEANUP_FAILED)
                except MemoryObservationError:
                    closed = 0
                if closed:
                    self._handles.remove(handle)
            if self._handles:
                _fail(FailureReason.CLEANUP_FAILED)
