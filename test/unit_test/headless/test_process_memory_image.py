"""Exercise image acquisition through fake native buffers without loading Windows APIs."""
import ctypes
import hashlib

import pytest

from je_auto_control.utils.process_memory.models import MemoryObservationError
from je_auto_control.utils.process_memory.windows_image import WindowsImageObserver
from je_auto_control.utils.process_memory.windows_image_native import FileBasicInfo, FileIdInfo, I64
from je_auto_control.utils.process_memory.windows_native import PTR, U32
from headless.test_process_memory_windows import Function, Kernel


class ImageKernel(Kernel):
    def __init__(self):
        super().__init__()
        self.image_path = "C:\\owned\\python.exe"
        self.data, self.position = b"measured image bytes", 0
        self.volume, self.file_id, self.changed = 9, b"f" * 16, 11
        self.file_handle, self.file_type = 92, 1
        self.short, self.read_success = False, True
        self.failed_closes = set()
        self.after_file_read = lambda: None
        self.path_failure, self.info_failure, self.size_override = False, False, None
        for name, implementation in {
            "QueryFullProcessImageNameW": self.image_name,
            "CreateFileW": lambda *args: self.file_handle,
            "GetFileType": lambda *args: self.file_type,
            "GetFileInformationByHandleEx": self.file_info,
            "GetFileSizeEx": self.file_size,
            "ReadFile": self.file_read,
            "CloseHandle": lambda handle: handle not in self.failed_closes,
        }.items():
            setattr(self, name, Function(implementation))

    def image_name(self, process, flags, buffer, length):
        buffer.value = self.image_path
        length._obj.value = len(self.image_path.encode("utf-16-le", "surrogatepass")) // 2
        return not self.path_failure

    def file_info(self, handle, kind, buffer, size):
        if kind == 18:
            buffer._obj.volume = self.volume
            buffer._obj.identifier[:] = self.file_id
        else:
            buffer._obj.created, buffer._obj.written = 1, 2
            buffer._obj.changed, buffer._obj.attributes = self.changed, 0x20
        return not self.info_failure

    def file_size(self, handle, size):
        size._obj.value = len(self.data) if self.size_override is None else self.size_override
        return True

    def file_read(self, handle, buffer, size, count, overlapped):
        amount = size - 1 if self.short else size
        raw = self.data[self.position:self.position + amount]
        ctypes.memmove(buffer, raw, len(raw))
        count._obj.value = len(raw)
        self.position += len(raw)
        self.after_file_read()
        return self.read_success


def observer(kernel, **options):
    return WindowsImageObserver(kernel=kernel, last_error=lambda: kernel.error, **options)


def measure(owner, **options):
    return owner.observe(42, max_bytes=1 << 20, timeout=5, checkpoint=lambda: None, **options)


def test_measures_actual_file_and_keeps_deny_write_delete_leases_until_close():
    kernel = ImageKernel()
    owner = observer(kernel)
    result = measure(owner)
    assert result.process.pid == 42 and result.process.birth == kernel.birth
    assert (result.volume, result.file_id, result.size) == (9, b"f" * 16, len(kernel.data))
    assert result.sha256 == hashlib.sha256(kernel.data).hexdigest()
    assert kernel.OpenProcess.calls == [(0x101000, False, 42)]
    assert kernel.CreateFileW.calls == [(kernel.image_path, 0x80000000, 1, None, 3, 0, None)]
    assert not kernel.CloseHandle.calls and not owner.pending_cleanup
    assert not kernel.ReadProcessMemory.calls
    assert kernel.image_path not in repr(result) and result.sha256 not in repr(result)
    assert "42" not in repr(result) and "ffff" not in repr(result)
    owner.close()
    owner.close()
    assert kernel.CloseHandle.calls == [(92,), (91,)]
    with pytest.raises(MemoryObservationError, match="target_changed"):
        measure(owner)


def test_native_abi_is_fixed_width_and_does_not_request_write_calls():
    kernel = ImageKernel()
    observer(kernel)
    assert ctypes.sizeof(FileIdInfo) == 24
    assert ctypes.sizeof(FileBasicInfo) == 40
    assert FileBasicInfo.attributes.offset == 32
    assert ctypes.sizeof(I64) == 8
    assert kernel.CreateFileW.restype is PTR
    assert kernel.ReadFile.argtypes == [PTR, PTR, U32, ctypes.POINTER(U32), PTR]
    assert kernel.QueryFullProcessImageNameW.argtypes[-1] is ctypes.POINTER(U32)


@pytest.mark.parametrize("field,value", [
    ("pid", 43), ("birth", 88), ("session", 8), ("machine", 0x014C),
    ("wait", 0), ("image_path", "C:\\replacement.exe"), ("file_id", b"g" * 16),
    ("volume", 10), ("changed", 12), ("size_override", 100),
])
def test_changes_during_read_publish_no_evidence_and_close_every_handle(field, value):
    kernel = ImageKernel()
    kernel.after_file_read = lambda: setattr(kernel, field, value)
    owner = observer(kernel)
    with pytest.raises(MemoryObservationError, match="target_changed"):
        measure(owner)
    assert kernel.CloseHandle.calls == [(92,), (91,)]
    assert not owner.pending_cleanup


@pytest.mark.parametrize("attribute,value,reason,closed", [
    ("open_value", 0, "target_changed", []),
    ("path_failure", True, "unsupported", [(91,)]),
    ("file_handle", -1, "unsupported", [(91,)]),
    ("file_handle", 0xFFFFFFFFFFFFFFFF, "unsupported", [(91,)]),
    ("file_type", 3, "unsupported", [(92,), (91,)]),
    ("info_failure", True, "unsupported", [(92,), (91,)]),
    ("size_override", -1, "unsupported", [(92,), (91,)]),
    ("size_override", (1 << 20) + 1, "budget_exceeded", [(92,), (91,)]),
    ("short", True, "partial_read", [(92,), (91,)]),
    ("read_success", False, "partial_read", [(92,), (91,)]),
])
def test_acquisition_and_read_failures_keep_closed_reason(attribute, value, reason, closed):
    kernel = ImageKernel()
    setattr(kernel, attribute, value)
    owner = observer(kernel)
    with pytest.raises(MemoryObservationError, match=reason):
        measure(owner)
    assert kernel.CloseHandle.calls == closed


def test_access_denial_is_distinct_and_does_not_read_file():
    kernel = ImageKernel()
    kernel.error, kernel.file_handle = 5, -1
    with pytest.raises(MemoryObservationError, match="access_denied"):
        measure(observer(kernel))
    assert not kernel.ReadFile.calls


def test_failed_close_tries_other_handles_and_retains_only_failed_ownership():
    kernel = ImageKernel()
    owner = observer(kernel)
    measure(owner)
    kernel.failed_closes.add(92)
    with pytest.raises(MemoryObservationError, match="cleanup_failed"):
        owner.close()
    assert owner.pending_cleanup and kernel.CloseHandle.calls == [(92,), (91,)]
    kernel.failed_closes.clear()
    owner.close()
    assert not owner.pending_cleanup and kernel.CloseHandle.calls[-1] == (92,)
    assert kernel.CloseHandle.calls.count((91,)) == 1


def test_failure_and_cancellation_do_not_orphan_failed_cleanup():
    kernel = ImageKernel()
    kernel.failed_closes.add(92)
    owner = observer(kernel)

    class Cancelled(Exception):
        pass

    def checkpoint():
        if kernel.ReadFile.calls:
            raise Cancelled("cancelled")

    with pytest.raises(Cancelled):
        owner.observe(42, max_bytes=100, timeout=5, checkpoint=checkpoint)
    assert owner.pending_cleanup
    assert kernel.CloseHandle.calls == [(92,), (91,)]
    kernel.failed_closes.clear()
    owner.close()
    assert not owner.pending_cleanup


def test_deadline_after_read_returns_no_evidence_and_retires():
    kernel = ImageKernel()
    now = [1.0]
    kernel.after_file_read = lambda: now.__setitem__(0, 7.0)
    owner = observer(kernel, clock=lambda: now[0])
    with pytest.raises(MemoryObservationError, match="deadline_exceeded"):
        measure(owner)
    assert kernel.CloseHandle.calls == [(92,), (91,)]


@pytest.mark.parametrize("pid,limit,timeout", [(True, 10, 1), (0, 10, 1), (1 << 32, 10, 1),
                                              (42, True, 1), (42, 1 << 30, 1), (42, 10, float("inf")),
                                              (42, 10, float("nan")), (42, 10, 0)])
def test_invalid_bounds_make_no_native_calls(pid, limit, timeout):
    kernel = ImageKernel()
    with pytest.raises(MemoryObservationError):
        observer(kernel).observe(pid, max_bytes=limit, timeout=timeout, checkpoint=lambda: None)
    assert not kernel.OpenProcess.calls


def test_multi_chunk_hash_is_measured_and_no_expected_digest_is_accepted():
    kernel = ImageKernel()
    kernel.data = b"a" * 65536 + b"different final chunk"
    owner = observer(kernel)
    result = measure(owner)
    assert result.sha256 == hashlib.sha256(kernel.data).hexdigest()
    assert [call[2] for call in kernel.ReadFile.calls] == [65536, 21]
    owner.close()


def test_reentrant_retirement_at_checkpoint_cannot_publish_evidence():
    kernel = ImageKernel()
    owner = observer(kernel)

    def retire():
        if kernel.ReadFile.calls:
            owner.close()

    with pytest.raises(MemoryObservationError, match="target_changed"):
        owner.observe(42, max_bytes=100, timeout=5, checkpoint=retire)
    assert kernel.CloseHandle.calls == [(92,), (91,)]


def test_pid_mismatch_before_file_open_fails_closed():
    kernel = ImageKernel()
    kernel.pid = 43
    with pytest.raises(MemoryObservationError, match="target_changed"):
        measure(observer(kernel))
    assert not kernel.CreateFileW.calls


def test_32bit_owner_refuses_64bit_target_without_file_read():
    kernel = ImageKernel()
    with pytest.raises(MemoryObservationError, match="unsupported"):
        measure(observer(kernel, caller_bits=32))
    assert not kernel.CreateFileW.calls and kernel.CloseHandle.calls == [(91,)]



@pytest.mark.parametrize("path", ["C:\\owned\\\U0001f680.exe", "C:\\owned\\\ud800.exe"])
def test_image_name_lengths_use_windows_utf16_units(path):
    kernel = ImageKernel()
    kernel.image_path = path
    owner = observer(kernel)
    result = measure(owner)
    assert result.size == len(kernel.data)
    assert kernel.CreateFileW.calls[0][0] == path
    owner.close()


def test_retirement_before_first_acquisition_is_terminal():
    kernel = ImageKernel()
    owner = observer(kernel)
    owner.close()
    with pytest.raises(MemoryObservationError, match="target_changed"):
        measure(owner)
    assert not kernel.OpenProcess.calls


def test_successive_observers_measure_changed_bytes_instead_of_reusing_identity_digest():
    digests = []
    for contents in (b"one", b"two"):
        kernel = ImageKernel()
        kernel.data = contents
        owner = observer(kernel)
        digests.append(measure(owner).sha256)
        owner.close()
    assert digests == [hashlib.sha256(value).hexdigest() for value in (b"one", b"two")]


def test_both_failed_closes_remain_owned_after_acquisition_failure():
    kernel = ImageKernel()
    kernel.info_failure = True
    kernel.failed_closes.update((91, 92))
    owner = observer(kernel)
    with pytest.raises(MemoryObservationError, match="unsupported"):
        measure(owner)
    assert owner.pending_cleanup and kernel.CloseHandle.calls == [(92,), (91,)]
    kernel.failed_closes.clear()
    owner.close()
    assert kernel.CloseHandle.calls == [(92,), (91,), (92,), (91,)]


def test_import_never_loads_kernel_or_registers_public_tools(monkeypatch):
    import importlib
    import je_auto_control.utils.process_memory.windows_image_native as native

    def forbidden(*args, **kwargs):
        raise AssertionError("native loader must not run during import")

    monkeypatch.setattr(ctypes, "WinDLL", forbidden, raising=False)
    importlib.reload(native)
    importlib.reload(importlib.import_module("je_auto_control.utils.process_memory.windows_image"))


def test_unknown_architecture_is_unsupported_before_file_acquisition():
    kernel = ImageKernel()
    kernel.machine = 0xFFFF
    with pytest.raises(MemoryObservationError, match="unsupported"):
        measure(observer(kernel))
    assert not kernel.CreateFileW.calls and not kernel.ReadFile.calls


@pytest.mark.parametrize("operation,reason", [("CreateFileW", "unsupported"), ("ReadFile", "partial_read"),
                                            ("GetProcessTimes", "target_changed"),
                                            ("GetFileInformationByHandleEx", "unsupported")])
def test_native_exceptions_are_closed_and_never_expose_private_data(operation, reason):
    kernel = ImageKernel()

    def fail(*args):
        raise OSError("private-path-address-123")

    getattr(kernel, operation).implementation = fail
    owner = observer(kernel)
    with pytest.raises(MemoryObservationError) as error:
        measure(owner)
    assert str(error.value) == reason
    assert "private" not in repr(error.value)
    assert not owner.pending_cleanup


def test_close_exceptions_try_every_handle_and_preserve_checkpoint_exception():
    kernel = ImageKernel()
    owner = observer(kernel)

    def close(handle):
        if handle == 92:
            raise RuntimeError("private-file-path")
        return True

    kernel.CloseHandle.implementation = close

    class Cancelled(Exception):
        pass

    def checkpoint():
        if kernel.ReadFile.calls:
            raise Cancelled("checkpoint cancellation")

    with pytest.raises(Cancelled, match="checkpoint cancellation"):
        owner.observe(42, max_bytes=100, timeout=5, checkpoint=checkpoint)
    assert kernel.CloseHandle.calls == [(92,), (91,)] and owner.pending_cleanup
    kernel.CloseHandle.implementation = lambda handle: True
    owner.close()
    assert not owner.pending_cleanup
