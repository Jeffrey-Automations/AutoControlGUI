"""A pinned image is launched only from a path no other account can redirect or plant a DLL beside.

The lease fixes the image's bytes, but CreateProcess resolves the path again by
name and the loader searches the image's directory first. These tests drive the
location check through a fake security source, so they run on every platform.
"""
import hashlib

import pytest

from je_auto_control.utils.agent_runtime import native_channel, owned_channel_launch, uia_launch
from je_auto_control.utils.process_memory.models import MemoryObservationError
from je_auto_control.utils.process_memory.windows_image import WindowsImageObserver
from je_auto_control.utils.process_memory.windows_image_trust import (
    AccessEntry, DirectorySecurity, local_drive_path, require_trusted_image,
)
from headless.test_process_memory_image import ImageKernel, observer

SYSTEM, ADMINS, USER, OTHER = "S-1-5-18", "S-1-5-32-544", "S-1-5-21-1-2-3-1001", "S-1-5-11"
FULL, READ, APPEND_ONLY = 0x1F01FF, 0x1200A9, 0x4
IMAGE = "C:\\Fixtures\\app\\fixture.exe"


def _safe(*extra):
    return DirectorySecurity(SYSTEM, (AccessEntry(0, 0, FULL, SYSTEM), AccessEntry(0, 0, FULL, ADMINS),
                                      AccessEntry(0, 0, FULL, USER), AccessEntry(0, 0, READ, OTHER), *extra), 0x10)


class Source:
    def __init__(self, final=None, **directories):
        self.final = final or "\\\\?\\" + IMAGE
        self.directories = directories
        self.asked = []

    def user_sid(self):
        return USER

    def final_path(self, handle):
        return self.final

    def directory(self, path):
        self.asked.append(path)
        return self.directories.get(path, _safe())


def test_protected_chain_is_checked_from_the_drive_root_down():
    source = Source()
    require_trusted_image(IMAGE, 7, source)
    assert source.asked == ["C:\\", "C:\\Fixtures", "C:\\Fixtures\\app"]


@pytest.mark.parametrize("security", [
    _safe(AccessEntry(0, 0, 0x10000, OTHER)),  # DELETE: rename the directory away
    _safe(AccessEntry(0, 0, 0x40, OTHER)),  # FILE_DELETE_CHILD
    _safe(AccessEntry(0, 0, 0x2, OTHER)),  # FILE_ADD_FILE: plant a DLL
    _safe(AccessEntry(0, 0, 0x40000, OTHER)),  # WRITE_DAC
    _safe(AccessEntry(0, 0, 0x10000000, OTHER)),  # GENERIC_ALL
    _safe(AccessEntry(0x9, 0, 0x1301BF, OTHER)),  # callback allow ACE, Modify
    _safe(AccessEntry(0x5, 0, READ, None)),  # an object allow ACE this check cannot read
    DirectorySecurity(SYSTEM, None, 0x10),  # NULL DACL: everyone has everything
    DirectorySecurity(OTHER, _safe().entries, 0x10),  # owner can rewrite the ACL
    DirectorySecurity(SYSTEM, _safe().entries, 0x10 | 0x400),  # a junction or symlink
    DirectorySecurity(SYSTEM, _safe().entries, 0x20),  # not a directory
], ids=["delete", "delete-child", "add-file", "write-dac", "generic-all", "callback", "object", "null-dacl",
        "owner", "reparse", "file"])
@pytest.mark.parametrize("level", ["C:\\", "C:\\Fixtures", "C:\\Fixtures\\app"])
def test_any_directory_another_account_can_change_refuses_the_image(security, level):
    with pytest.raises(MemoryObservationError, match="unsupported"):
        require_trusted_image(IMAGE, 7, Source(**{level: security}))


def test_grants_that_cannot_redirect_the_path_are_accepted():
    # A drive root lets Authenticated Users create folders (append data only), and the
    # Modify grant they get on new subfolders is inherit-only. A deny or audit ACE grants nothing.
    root = _safe(AccessEntry(0, 0, APPEND_ONLY, OTHER), AccessEntry(0, 0x08 | 0x03, 0x1301BF, OTHER),
                 AccessEntry(1, 0, FULL, OTHER), AccessEntry(2, 0, FULL, OTHER))
    require_trusted_image(IMAGE, 7, Source(**{"C:\\": root}))


def test_the_running_user_may_own_and_write_the_deployment():
    owned = DirectorySecurity(USER, (AccessEntry(0, 0, FULL, USER),), 0x10)
    require_trusted_image(IMAGE, 7, Source(**{"C:\\Fixtures": owned, "C:\\Fixtures\\app": owned}))


@pytest.mark.parametrize("final", [
    "\\\\?\\C:\\Elsewhere\\fixture.exe",  # a junction somewhere in the requested path
    "\\\\?\\C:\\FIXTUR~1\\app\\fixture.exe",  # a short name stands for something else
    "\\\\?\\UNC\\host\\share\\fixture.exe",  # a mapped network drive
])
def test_the_leased_file_must_be_the_file_the_path_names(final):
    with pytest.raises(MemoryObservationError):
        require_trusted_image(IMAGE, 7, Source(final=final))


def test_final_path_comparison_ignores_case_only():
    require_trusted_image(IMAGE, 7, Source(final="\\\\?\\c:\\fixtures\\APP\\Fixture.EXE"))


@pytest.mark.parametrize("path", [
    "\\\\host\\share\\fixture.exe", "//host/share/fixture.exe", "\\\\.\\pipe\\fixture",
    "\\\\?\\C:\\fixture.exe", "fixture.exe", "C:fixture.exe", "C:\\", "\\fixture.exe", "C:\\a\0.exe",
])
def test_only_drive_letter_paths_reach_the_security_source(path):
    source = Source()
    with pytest.raises(MemoryObservationError, match="unsupported"):
        require_trusted_image(path, 7, source)
    assert not source.asked


def test_parent_segments_are_resolved_before_the_chain_is_checked():
    assert local_drive_path("C:\\Fixtures\\other\\..\\app\\fixture.exe") == IMAGE


def test_lease_asks_the_location_check_before_reading_any_byte():
    kernel = ImageKernel()
    leased = observer(kernel).lease(kernel.image_path, max_bytes=1 << 20, timeout=5, checkpoint=lambda: None)
    assert kernel.trust_calls == [(kernel.image_path, kernel.file_handle, 0)]
    assert leased.sha256 == hashlib.sha256(kernel.data).hexdigest()


def test_untrusted_location_refuses_the_lease_and_closes_its_handle():
    kernel = ImageKernel()
    kernel.untrusted = True
    owner = observer(kernel)
    with pytest.raises(MemoryObservationError, match="unsupported"):
        owner.lease(kernel.image_path, max_bytes=1 << 20, timeout=5, checkpoint=lambda: None)
    assert kernel.position == 0 and not owner.pending_cleanup
    assert (kernel.file_handle,) in kernel.CloseHandle.calls


def test_an_injected_kernel_without_a_location_check_cannot_lease():
    # Only the native observer binds the native check; a fake kernel never falls back to "trusted".
    kernel = ImageKernel()
    owner = WindowsImageObserver(kernel=kernel, last_error=lambda: kernel.error)
    with pytest.raises(MemoryObservationError, match="unsupported"):
        owner.lease(kernel.image_path, max_bytes=1 << 20, timeout=5, checkpoint=lambda: None)
    assert kernel.position == 0


def test_pinned_child_starts_in_its_directory_with_a_minimal_environment():
    environ = {"SystemRoot": "C:\\Windows", "TEMP": "C:\\T", "AWS_SECRET_ACCESS_KEY": "x",
               "ANTHROPIC_API_KEY": "y", "PATH": "C:\\Users\\me\\bin;C:\\Windows", "PYTHONPATH": "C:\\p"}
    options = owned_channel_launch.pinned_child_options(IMAGE, environ)
    assert options["cwd"] == "C:\\Fixtures\\app"
    assert options["env"] == {"SYSTEMROOT": "C:\\Windows", "TEMP": "C:\\T",
                              "PATH": "C:\\Windows\\System32;C:\\Windows;C:\\Windows\\System32\\Wbem"}


def test_default_fixture_channels_pass_the_pinned_options_to_the_process(monkeypatch):
    started = []

    def popen(argv, **options):
        started.append((argv, options))
        raise OSError("not launched in a unit test")

    monkeypatch.setattr(native_channel.subprocess, "Popen", popen)
    for factory in (owned_channel_launch.pinned_channel, uia_launch.pinned_uia_channel):
        with pytest.raises(OSError):
            factory([IMAGE, "--challenge", "00"])
    assert len(started) == 2
    for argv, options in started:
        assert argv == [IMAGE, "--challenge", "00"]
        assert options["cwd"] == "C:\\Fixtures\\app"
        assert "PATH" not in options["env"] or "Users" not in options["env"]["PATH"]
        assert not {"AWS_SECRET_ACCESS_KEY", "PYTHONPATH"} & set(options["env"])
