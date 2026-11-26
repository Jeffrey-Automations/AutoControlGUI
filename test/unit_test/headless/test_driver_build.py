"""The driver is built with Nuitka as one windowless executable, and no binary lives in the repo."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DRIVER = ROOT / "autocontrol_driver"


def _build_module():
    spec = importlib.util.spec_from_file_location("build_driver", DRIVER / "build_driver.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_windows_build_is_one_windowless_executable_with_the_icon(tmp_path):
    command = _build_module().nuitka_command("win32", tmp_path, python="py")
    assert command[:3] == ["py", "-m", "nuitka"]
    assert "--onefile" in command and "--windows-console-mode=disable" in command
    assert f"--windows-icon-from-ico={DRIVER / 'je_driver_icon.ico'}" in command
    assert "--output-filename=AutoControlDriver.exe" in command and f"--output-dir={tmp_path}" in command
    assert command[-1] == str(DRIVER / "generate_autocontrol_driver.py")


def test_the_linux_build_has_no_windows_flags(tmp_path):
    command = _build_module().nuitka_command("linux", tmp_path, python="py")
    assert "--onefile" in command and "--output-filename=AutoControlDriver" in command
    assert not any(flag.startswith("--windows-") for flag in command)


def test_the_build_takes_the_whole_package_and_leaves_the_gui_out(tmp_path):
    command = _build_module().nuitka_command("win32", tmp_path, python="py")
    assert "--include-package=je_auto_control" in command
    assert "--nofollow-import-to=je_auto_control.gui" in command and "--nofollow-import-to=PySide6" in command


def test_no_prebuilt_driver_is_kept_in_the_repository():
    # A committed binary ships whatever server it was built from; the Driver workflow builds them.
    kept = [path.name for path in DRIVER.iterdir() if path.suffix in {".exe", ""} and path.is_file()]
    assert not kept, f"prebuilt drivers in the repository: {kept}"
