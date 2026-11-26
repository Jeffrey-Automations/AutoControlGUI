"""Build the AutoControl socket driver as one windowless executable with Nuitka.

The driver is ``generate_autocontrol_driver.py``: it starts the authenticated TCP
socket server and stays up until a client sends ``quit_server``. Built here, it
is a single file with no console window on Windows (``--windows-console-mode=
disable``) and a plain one-file binary on Linux. The ``Driver`` workflow
(``.github/workflows/driver.yml``) runs this on Windows and Ubuntu runners; the
binaries are not kept in the repository, so none can lag behind the server.

    python autocontrol_driver/build_driver.py [--output-dir DIR]
"""
import argparse
import subprocess  # nosec B404  # reason: runs this interpreter's Nuitka on a fixed argv
import sys
from pathlib import Path
from typing import List

HERE = Path(__file__).resolve().parent
ENTRY = HERE / "generate_autocontrol_driver.py"
ICON = HERE / "je_driver_icon.ico"
#: Modules the driver never needs: the Qt GUI is loaded only by start_autocontrol_gui().
EXCLUDED = ("je_auto_control.gui", "PySide6")


def output_name(platform: str) -> str:
    """The executable's file name on ``platform`` (a ``sys.platform`` value)."""
    return "AutoControlDriver.exe" if platform.startswith("win") else "AutoControlDriver"


def nuitka_command(platform: str, output_dir: Path, python: str = sys.executable) -> List[str]:
    """The Nuitka argv that builds the driver for ``platform`` into ``output_dir``."""
    command = [python, "-m", "nuitka", "--onefile", "--assume-yes-for-downloads",
               # The facade resolves most names on first use, so imports alone do not reach every
               # command module an action file may name; the whole package goes in.
               "--include-package=je_auto_control",
               f"--output-dir={output_dir}", f"--output-filename={output_name(platform)}"]
    command += [f"--nofollow-import-to={module}" for module in EXCLUDED]
    if platform.startswith("win"):
        command += ["--windows-console-mode=disable", f"--windows-icon-from-ico={ICON}"]
    return command + [str(ENTRY)]


def main(argv: List[str] | None = None) -> int:
    """Build the driver for the running platform; Nuitka's exit status."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=HERE / "dist")
    args = parser.parse_args(argv)
    command = nuitka_command(sys.platform, args.output_dir.resolve())
    # argv is this interpreter, Nuitka's fixed flags and two paths inside this directory. No shell.
    return subprocess.run(command, check=False).returncode  # nosec B603  # reason: fixed argv


if __name__ == "__main__":
    sys.exit(main())
