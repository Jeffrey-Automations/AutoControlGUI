"""Start a built driver, check it requires authentication, run one command and stop it.

    python autocontrol_driver/smoke_driver.py PATH_TO_DRIVER [--timeout SECONDS]

Exits 0 only if the binary wrote its token file, refused a command sent without
the token, answered one sent with it with the expected value, accepted
``quit_server`` and then exited with code 0. Any other outcome exits 1 after
printing what the driver answered and its exit code.
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
#: ``AC_set_var`` answers with the value it set.
SMOKE_VALUE = "driver-smoke-ok"
EXPECTED_REPLY = [SMOKE_VALUE]


class SmokeFailure(Exception):
    """The driver did not behave as a released driver must."""


def _wait_for(condition, timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise SmokeFailure(f"timed out waiting for {what}")
        time.sleep(0.5)


def _check(driver: subprocess.Popen, timeout: float) -> None:
    token_file = default_token_path(PORT)
    _wait_for(lambda: token_file.exists() or driver.poll() is not None, timeout, "the token file")
    if driver.poll() is not None:
        raise SmokeFailure(f"the driver exited with {driver.returncode} before it was ready")
    refused = send_socket_command([["AC_screen_size"]], port=PORT, require_auth=False, timeout=timeout)
    if not any("authentication required" in line for line in refused):
        raise SmokeFailure(f"a command without the token was not refused: {refused}")
    command = [["AC_set_var", {"name": "driver_smoke", "value": SMOKE_VALUE}]]
    reply = send_socket_command(command, port=PORT, timeout=timeout)
    print("authenticated reply:", reply)
    if reply != EXPECTED_REPLY:
        raise SmokeFailure(f"the authenticated command answered {reply}, expected {EXPECTED_REPLY}")
    # quit_server is answered only when it is refused.
    quit_reply = send_socket_command("quit_server", port=PORT, timeout=timeout)
    if quit_reply:
        raise SmokeFailure(f"quit_server was refused: {quit_reply}")
    try:
        driver.wait(timeout)
    except subprocess.TimeoutExpired:
        raise SmokeFailure(f"the driver was still running {timeout:g}s after quit_server") from None
    if driver.returncode != 0:
        raise SmokeFailure(f"the driver exited with {driver.returncode} after quit_server, expected 0")


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
    except SmokeFailure as failure:
        print("smoke test failed:", failure, file=sys.stderr)
        return 1
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait(10)
        print("driver exited with", driver.returncode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
