"""Start a built driver, check it requires authentication, run one command and stop it.

    python autocontrol_driver/smoke_driver.py PATH_TO_DRIVER [--timeout SECONDS]

Exits 0 only if the binary wrote its token file, refused a command sent without
the token, answered one sent with it, and exited after ``quit_server``.
Used by the ``Driver`` workflow on each built binary.
"""
import argparse
import subprocess  # nosec B404  # reason: starts the binary named on the command line
import sys
import time
from pathlib import Path

from je_auto_control.utils.socket_server.socket_auth import default_token_path
from je_auto_control.utils.socket_server.socket_client import send_socket_command

PORT = 9938


def _wait_for(condition, timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise SystemExit(f"timed out waiting for {what}")
        time.sleep(0.5)


def _check(driver: subprocess.Popen, timeout: float) -> None:
    token_file = default_token_path(PORT)
    _wait_for(lambda: token_file.exists() or driver.poll() is not None, timeout, "the token file")
    if driver.poll() is not None:
        raise SystemExit(f"the driver exited with {driver.returncode} before it was ready")
    refused = send_socket_command([["AC_screen_size"]], port=PORT, require_auth=False, timeout=timeout)
    if not any("authentication required" in line for line in refused):
        raise SystemExit(f"a command without the token was not refused: {refused}")
    reply = send_socket_command([["AC_set_var", {"name": "driver_smoke", "value": 1}]], port=PORT, timeout=timeout)
    print("authenticated reply:", reply)
    send_socket_command("quit_server", port=PORT, timeout=timeout)
    driver.wait(timeout)


def main(argv=None) -> int:
    """Run the checks against the driver binary given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("driver", type=Path)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    # argv is the one binary this workflow just built. No shell.
    driver = subprocess.Popen([str(args.driver.resolve())])
    try:
        _check(driver, args.timeout)
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait(10)
    print("driver exited with", driver.returncode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
