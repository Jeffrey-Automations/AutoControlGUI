"""Owned-launch attestation through fake native buffers: no process is started or read."""
import hashlib

import pytest

from je_auto_control.utils.exception.control_signals import OperationCancelledError
from je_auto_control.utils.process_memory.models import FailureReason, MemoryObservationError
from je_auto_control.utils.process_memory.windows_launch import (
    LaunchRecord, PinnedExecutable, launch_attested,
)
from headless.test_process_memory_image import ImageKernel, observer
from headless.test_process_memory_windows import Function


class LaunchKernel(ImageKernel):
    """Every CreateFileW starts reading the image from its first byte."""

    def __init__(self):
        super().__init__()
        self.CreateFileW = Function(self.open_file)

    def open_file(self, *args):
        self.position = 0
        return self.file_handle


def pin(kernel, **changes):
    values = {"host": "owned-host", "session": "owned-session", "executable": "fixture",
              "version": "1", "sha256": hashlib.sha256(kernel.data).hexdigest()}
    values.update(changes)
    return PinnedExecutable(**values)


def lease_only(kernel):
    return observer(kernel).lease(kernel.image_path, max_bytes=1 << 20, timeout=5, checkpoint=lambda: None)


def attest(kernel, launcher=None, pinned=None, **options):
    launched = []

    def launch(path):
        launched.append(path)
        return LaunchRecord(42, kernel.birth)

    lease, watch = observer(kernel), observer(kernel)
    result = launch_attested(pinned or pin(kernel), kernel.image_path, launcher or launch,
                             lease=lease, observer=watch, max_bytes=1 << 20, timeout=5,
                             checkpoint=lambda: None, **options)
    return result, launched, lease, watch


def test_a_lease_digests_the_file_before_any_process_exists():
    kernel = LaunchKernel()
    leased = lease_only(kernel)
    assert leased.sha256 == hashlib.sha256(kernel.data).hexdigest()
    assert (leased.volume, leased.file_id, leased.size) == (9, b"f" * 16, len(kernel.data))
    assert kernel.CreateFileW.calls == [(kernel.image_path, 0x80000000, 1, None, 3, 0, None)]
    assert not kernel.OpenProcess.calls
    assert not kernel.CloseHandle.calls
    assert leased.sha256 not in repr(leased)


@pytest.mark.parametrize("path", ["", "C:\\owned\\py" + chr(0) + ".exe", None, "x" * 32768],
                         ids=["empty", "nul", "none", "too-long"])
def test_a_lease_refuses_an_unusable_path_before_opening_it(path):
    kernel = LaunchKernel()
    owner = observer(kernel)
    with pytest.raises(MemoryObservationError, match="unsupported"):
        owner.lease(path, max_bytes=1 << 20, timeout=5, checkpoint=lambda: None)
    assert not kernel.CreateFileW.calls


def test_a_lease_that_sees_the_file_change_publishes_nothing():
    kernel = LaunchKernel()
    kernel.after_file_read = lambda: setattr(kernel, "changed", 12)
    owner = observer(kernel)
    with pytest.raises(MemoryObservationError, match="target_changed"):
        owner.lease(kernel.image_path, max_bytes=1 << 20, timeout=5, checkpoint=lambda: None)
    assert kernel.CloseHandle.calls == [(92,)]
    assert not owner.pending_cleanup


def test_an_owned_launch_of_the_pinned_file_is_attested():
    kernel = LaunchKernel()
    launch, launched, lease, watch = attest(kernel)
    identity = launch.identity
    assert launched == [kernel.image_path]
    assert (identity.host, identity.session, identity.executable, identity.version) == (
        "owned-host", "owned-session", "fixture", "1")
    assert (identity.pid, identity.birth, identity.architecture) == (42, kernel.birth, "x64")
    assert kernel.CloseHandle.calls == []  # both leases are held until close
    launch.close()
    assert sorted(kernel.CloseHandle.calls) == [(91,), (92,), (92,)]


def test_the_attestor_names_only_the_launched_process():
    from dataclasses import replace
    kernel = LaunchKernel()
    launch, *_ = attest(kernel)
    facts = launch.attestor._observed.process
    assert launch.attestor(facts) == launch.identity
    for change in ({"birth": facts.birth + 1}, {"pid": 43}, {"session_id": facts.session_id + 1}):
        with pytest.raises(MemoryObservationError, match="target_changed"):
            launch.attestor(replace(facts, **change))


def test_a_file_that_does_not_match_the_pin_is_never_launched():
    kernel = LaunchKernel()
    wrong = pin(kernel, sha256="0" * 64)
    with pytest.raises(MemoryObservationError, match="unsupported"):
        attest(kernel, pinned=wrong)
    assert kernel.CloseHandle.calls == [(92,)]  # the lease is closed; no process was opened
    assert not kernel.OpenProcess.calls


def test_a_child_running_a_different_file_than_the_leased_one_is_refused():
    kernel = LaunchKernel()

    def launch(path):
        kernel.file_id = b"g" * 16  # the image the child runs is another file
        return LaunchRecord(42, kernel.birth)

    with pytest.raises(MemoryObservationError, match="target_changed"):
        attest(kernel, launcher=launch)


@pytest.mark.parametrize("record", [LaunchRecord(43, 1), LaunchRecord(42, 1), (42, 1), LaunchRecord(0, 1)])
def test_a_launch_record_that_is_not_the_observed_child_is_refused(record):
    kernel = LaunchKernel()
    with pytest.raises(MemoryObservationError, match="target_changed"):
        attest(kernel, launcher=lambda path: record)


def test_launcher_failures_are_closed_and_interruptions_propagate():
    kernel = LaunchKernel()

    def broken(path):
        raise RuntimeError("SECRET C:\\owned\\python.exe --token abc")

    with pytest.raises(MemoryObservationError) as caught:
        attest(kernel, launcher=broken)
    assert caught.value.reason == FailureReason.UNSUPPORTED
    assert "SECRET" not in str(caught.value)
    signal = OperationCancelledError("stop")

    def cancelled(path):
        raise signal

    fresh = LaunchKernel()
    with pytest.raises(OperationCancelledError) as interrupted:
        attest(fresh, launcher=cancelled)
    assert interrupted.value is signal


@pytest.mark.parametrize("changes", [{"sha256": "A" * 64}, {"sha256": "0" * 63}, {"host": "bad host"},
                                     {"version": ""}])
def test_a_pin_must_be_a_lowercase_sha256_and_identifiers(changes):
    kernel = LaunchKernel()
    with pytest.raises(MemoryObservationError, match="unsupported"):
        pin(kernel, **changes)


class _Child:
    def __init__(self, pid, handle):
        self.pid, self._handle = pid, handle


def _popen_launcher(kernel, child_pid=42, **options):
    from je_auto_control.utils.process_memory.windows_launch import PopenLauncher
    started = []

    def popen(argv, **kwargs):
        started.append((argv, kwargs))
        return _Child(child_pid, 77)

    launcher = PopenLauncher(("--challenge", "00" * 16), kernel=kernel, last_error=lambda: kernel.error,
                             caller_bits=64, popen=popen, **options)
    return launcher, started


def test_the_popen_launcher_measures_the_handle_popen_holds():
    kernel = LaunchKernel()
    launcher, started = _popen_launcher(kernel, creationflags=0x08000000)
    record = launcher(kernel.image_path)
    assert record == LaunchRecord(42, kernel.birth)
    assert started == [([kernel.image_path, "--challenge", "00" * 16], {"shell": False, "creationflags": 0x08000000})]
    assert {call[0] for call in kernel.GetProcessTimes.calls} == {77}  # never a handle reopened by PID
    assert not kernel.OpenProcess.calls
    assert launcher.child.pid == 42


def test_the_popen_launcher_refuses_a_handle_for_another_pid_and_a_second_launch():
    kernel = LaunchKernel()
    launcher, _ = _popen_launcher(kernel, child_pid=43)
    with pytest.raises(MemoryObservationError, match="target_changed"):
        launcher(kernel.image_path)
    assert launcher.child.pid == 43  # still the caller's to end
    with pytest.raises(MemoryObservationError, match="unsupported"):
        launcher(kernel.image_path)


@pytest.mark.parametrize("arguments,options", [((1,), {}), ((), {"shell": True})])
def test_the_popen_launcher_takes_only_an_argv_list(arguments, options):
    from je_auto_control.utils.process_memory.windows_launch import PopenLauncher
    kernel = LaunchKernel()
    with pytest.raises(MemoryObservationError, match="unsupported"):
        PopenLauncher(arguments, kernel=kernel, last_error=lambda: 0, **options)


def test_an_owned_launch_through_the_popen_launcher_is_attested():
    kernel = LaunchKernel()
    launcher, _ = _popen_launcher(kernel)
    launch, *_ = attest(kernel, launcher=launcher)
    assert launch.identity.pid == 42
    assert launch.record == LaunchRecord(42, kernel.birth)
