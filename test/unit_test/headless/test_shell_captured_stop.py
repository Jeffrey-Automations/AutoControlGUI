"""A captured shell command (``AC_shell_to_var``, ``ac_shell``) ends when its run is stopped or cancelled.

``run_captured`` waited in one ``communicate(timeout=...)``: a stop reached
the run only after the program ended or the whole timeout passed.
"""
import subprocess
from concurrent.futures import CancelledError
import sys
import threading
import time

import pytest

from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.executor.run_control import ExecutionStopped, StopToken, stoppable_run
from je_auto_control.utils.shell_process import shell_exec
from je_auto_control.utils.shell_process.shell_exec import run_captured

_SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


def _later(action, delay=0.3):
    timer = threading.Timer(delay, action)
    timer.start()
    return timer


def _spy_kills(monkeypatch):
    killed = []
    real = shell_exec._kill_tree

    def spy(process):
        killed.append(process)
        real(process)

    monkeypatch.setattr(shell_exec, "_kill_tree", spy)
    return killed


def test_a_stop_ends_the_command_and_kills_it(monkeypatch):
    killed = _spy_kills(monkeypatch)
    token = StopToken("captured-stop")
    started = time.monotonic()
    with stoppable_run(token=token):
        _later(lambda: token.stop("test"))
        with pytest.raises(ExecutionStopped):
            run_captured(_SLEEPER, 60)
    assert time.monotonic() - started < 15
    assert len(killed) == 1 and killed[0].poll() is not None


def test_a_cancellation_ends_the_command_and_kills_it(monkeypatch):
    killed = _spy_kills(monkeypatch)
    token = CancellationToken(7)
    started = time.monotonic()
    with cancellation_scope(token):
        _later(token.cancel)
        with pytest.raises(CancelledError):
            run_captured(_SLEEPER, 60)
    assert time.monotonic() - started < 15
    assert len(killed) == 1 and killed[0].poll() is not None


def test_inside_a_run_output_and_input_still_arrive_whole():
    echo = [sys.executable, "-c", "import sys; data = sys.stdin.buffer.read(); sys.stdout.buffer.write(data[::-1])"]
    with stoppable_run(token=StopToken("captured-echo")):
        done = run_captured(echo, 30, input_bytes=b"abc" * 1000)
    assert done.returncode == 0 and done.stdout == (b"abc" * 1000)[::-1]


def test_inside_a_run_the_timeout_still_applies(monkeypatch):
    killed = _spy_kills(monkeypatch)
    with stoppable_run(token=StopToken("captured-timeout")):
        with pytest.raises(subprocess.TimeoutExpired):
            run_captured(_SLEEPER, 0.5)
    assert len(killed) == 1


def test_outside_any_run_one_wait_is_used(monkeypatch):
    waits = []
    real = subprocess.Popen.communicate

    def spy(self, input=None, timeout=None):
        waits.append(timeout)
        return real(self, input, timeout)

    monkeypatch.setattr(subprocess.Popen, "communicate", spy)
    done = run_captured([sys.executable, "-c", "print('ok')"], 30)
    assert done.stdout.strip() == b"ok" and waits == [30]


def test_a_stopped_ac_shell_to_var_ends_the_script_promptly():
    from je_auto_control.utils.executor.action_executor import Executor
    executor = Executor()
    token = StopToken("captured-script")
    started = time.monotonic()
    _later(lambda: token.stop("test"))
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        executor.execute_action([["AC_shell_to_var", {"command": _SLEEPER, "timeout": 60}],
                                 ["AC_set_var", {"name": "after", "value": 1}]])
    assert time.monotonic() - started < 15
    assert executor.variables.get("after") is None
