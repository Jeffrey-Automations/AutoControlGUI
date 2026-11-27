"""The driver smoke test fails unless the driver answered as expected and exited cleanly.

It used to print the authenticated reply and the driver's exit code and return
0 whatever they were, so a driver that answered every command with an error,
or crashed on ``quit_server``, still passed the release check. The socket and
the driver process are doubles here: nothing is started and no port is opened.
"""
import importlib.util
import subprocess  # nosec B404  # reason: only for TimeoutExpired; no process is started
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
REFUSED = ["authentication required: send AUTH <token> first"]


def _smoke_module():
    spec = importlib.util.spec_from_file_location("smoke_driver", ROOT / "autocontrol_driver" / "smoke_driver.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Driver:
    """A driver process that is running until ``quit_server`` reaches it."""

    def __init__(self):
        self.returncode = None
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("driver", timeout)
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def _run(monkeypatch, tmp_path, *, reply, quit_reply=(), exit_code=0, exits_on_quit=True):
    module = _smoke_module()
    token_file = tmp_path / "socket_server_9938.token"
    token_file.write_text("t" * 32, encoding="utf-8")
    driver = _Driver()
    sent = []

    def send(command, port, require_auth=True, timeout=30.0):
        sent.append(command)
        if command == "quit_server":
            if exits_on_quit and not quit_reply:
                driver.returncode = exit_code
            return list(quit_reply)
        return list(REFUSED) if not require_auth else list(reply)

    monkeypatch.setattr(module, "default_token_path", lambda _port: token_file)
    monkeypatch.setattr(module, "send_socket_command", send)
    monkeypatch.setattr(module, "subprocess", types.SimpleNamespace(
        Popen=lambda argv: driver, TimeoutExpired=subprocess.TimeoutExpired))
    code = module.main([str(tmp_path / "driver.exe"), "--timeout", "0.1"])
    return code, driver, sent


def test_a_driver_that_answers_and_exits_cleanly_passes(monkeypatch, tmp_path):
    module = _smoke_module()
    code, driver, sent = _run(monkeypatch, tmp_path, reply=list(module.EXPECTED_REPLY))
    assert code == 0
    assert sent[-1] == "quit_server" and not driver.killed


@pytest.mark.parametrize("case", [
    {"reply": ["KeyError('name')"]},
    {"reply": []},
    {"reply": None, "exit_code": 9},
    {"reply": None, "quit_reply": ["forbidden: quit_server needs 'admin'"]},
    {"reply": None, "exits_on_quit": False},
], ids=["action-error", "no-reply", "exit-9", "quit-refused", "no-exit"])
def test_any_failed_check_fails_the_smoke_test_and_keeps_the_output(monkeypatch, tmp_path, capsys, case):
    module = _smoke_module()
    if case["reply"] is None:
        case = {**case, "reply": list(module.EXPECTED_REPLY)}
    code, driver, _sent = _run(monkeypatch, tmp_path, **case)
    assert code != 0
    output = capsys.readouterr()
    text = output.out + output.err
    assert "smoke test failed" in text
    for line in [*case["reply"], *case.get("quit_reply", ())]:
        assert line in text
    assert driver.returncode is not None   # never left running
    assert f"driver exited with {driver.returncode}" in text
