"""A stop ends the two subprocess helpers that used to wait out their timeout.

``run_capture_helper`` (USB enumeration, the Wayland capture tool) looked only
at a cancellation scope, and ``AdbClient.run`` (every ``AC_android_*`` command
and the Android extension operations) was a plain ``subprocess.run``. Inside a
stoppable run a stop now ends either within one 0.1 s slice. Every process
here is a fake whose ``communicate`` blocks for at most 1 s: no real program
runs and nothing touches a device.
"""
import subprocess  # nosec B404  # reason: only fake processes and CompletedProcess types are used
import threading
import time

import pytest

from je_auto_control.android import adb_client
from je_auto_control.utils import cancellable_process
from je_auto_control.utils.executor.run_control import ExecutionStopped, StopToken, stoppable_run
from je_auto_control.utils.shell_process import shell_exec

_BLOCK_S = 1.0
_PROMPT_S = 0.7


class _HungProcess:
    """A process that never ends by itself; ``kill`` ends it."""

    pid = 424242

    def __init__(self) -> None:
        self.returncode = None
        self.killed = threading.Event()
        self.stdout = self.stderr = None
        self.waits = []

    def communicate(self, *_input, timeout=None):
        self.waits.append(timeout)
        if self.killed.wait(min(_BLOCK_S, timeout if timeout is not None else _BLOCK_S)):
            self.returncode = -9
            return b"", b""
        raise subprocess.TimeoutExpired("fake", timeout)

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed.set()

    terminate = kill


def _stop_soon(token: StopToken) -> None:
    timer = threading.Timer(0.1, token.stop, ("test",))
    timer.daemon = True
    timer.start()


def test_capture_helper_is_ended_by_a_run_stop(monkeypatch):
    process = _HungProcess()
    monkeypatch.setattr(cancellable_process.subprocess, "Popen", lambda *_a, **_k: process)
    signalled = []
    monkeypatch.setattr(cancellable_process, "_signal_owned",
                        lambda proc, hard: (signalled.append(hard), proc.kill()))
    token = StopToken("capture-stop")
    _stop_soon(token)
    began = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        cancellable_process.run_capture_helper(["lsusb"], 30.0)
    assert time.monotonic() - began < _PROMPT_S
    assert signalled == [False]                      # the owned group was asked to end, then reaped
    assert max(process.waits[:-1]) <= 0.1 + 1e-9     # the wait came in short slices


def test_capture_helper_outside_a_run_is_unchanged(monkeypatch):
    class _Done(_HungProcess):
        def communicate(self, *_input, timeout=None):
            self.waits.append(timeout)
            self.returncode = 0
            return b"out", b""

    process = _Done()
    monkeypatch.setattr(cancellable_process.subprocess, "Popen", lambda *_a, **_k: process)
    completed = cancellable_process.run_capture_helper(["lsusb"], 7.0)
    assert completed.stdout == b"out"
    assert process.waits == [pytest.approx(7.0, abs=0.5)]   # one wait for the whole timeout


@pytest.fixture
def adb(tmp_path):
    fake = tmp_path / "adb"
    fake.write_text("")
    return adb_client.AdbClient(adb_path=str(fake), timeout_s=30.0)


def test_adb_command_is_ended_by_a_run_stop_and_only_the_client_is_killed(monkeypatch, adb):
    process = _HungProcess()
    monkeypatch.setattr(shell_exec.subprocess, "Popen", lambda *_a, **_k: process)
    monkeypatch.setattr(shell_exec, "_kill_tree",
                        lambda _p: pytest.fail("the adb server the client started must survive"))
    token = StopToken("adb-stop")
    _stop_soon(token)
    began = time.monotonic()
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        adb.shell("getprop ro.build.version.sdk")
    assert time.monotonic() - began < _PROMPT_S
    assert process.killed.is_set()


def test_adb_command_outside_a_run_is_a_plain_subprocess_run(monkeypatch, adb):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs["timeout"]))
        return subprocess.CompletedProcess(cmd, 0, b"34\n", b"")  # nosemgrep  # reason: a fake result, runs nothing

    monkeypatch.setattr(adb_client.subprocess, "run", run)
    assert adb.shell("getprop ro.build.version.sdk") == "34\n"
    assert calls == [([adb.adb_path, "shell", "getprop ro.build.version.sdk"], 30.0)]
