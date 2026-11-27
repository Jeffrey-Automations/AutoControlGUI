"""A run's secrets stay masked in shell output that arrives after the run ended. No Qt.

The reader threads queued stdout / stderr in plaintext, and the queue was only
written to the log when the next ``exec_shell`` (or ``pull_text``) drained it.
A program that printed a value its run had resolved after that run's mask had
closed therefore put the value into the log in plaintext. The readers now hold
their run's mask until both streams end, and mask each line as it is read.
The child processes here are fakes whose output is released on cue.
"""
import io
import logging
import threading

import pytest

from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.logging.secret_scope import (
    SecretLogScope, remember_secret, secret_log_scope,
)
from je_auto_control.utils.shell_process import shell_exec

FIRST = "first-run-private-value"
SECOND = "second-run-private-value"


class _GatedStream:
    """A pipe whose lines become readable only once ``gate`` is set."""

    def __init__(self, text: str, gate: threading.Event) -> None:
        self._lines = [line.encode("utf-8") for line in text.splitlines(keepends=True)]
        self._gate = gate

    def readline(self, _size: int = -1) -> bytes:
        if not self._gate.wait(5):
            return b""
        return self._lines.pop(0) if self._lines else b""


class _FakeProcess:
    pid = 1

    def __init__(self, secret: str, gate: threading.Event) -> None:
        self.stdout = _GatedStream(f"out token={secret}\n", gate)
        self.stderr = _GatedStream(f"err token={secret}\n", gate)
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def log_text():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    autocontrol_logger.addHandler(handler)
    try:
        yield stream.getvalue
    finally:
        autocontrol_logger.removeHandler(handler)
        handler.close()


def _join_readers(manager) -> None:
    for reader in (manager.read_program_output_from_thread, manager.read_program_error_output_from_thread):
        reader.join(timeout=5)
        assert not reader.is_alive()


def test_output_after_each_run_ends_is_logged_masked(monkeypatch, log_text):
    gates = [threading.Event(), threading.Event()]
    processes = iter([_FakeProcess(FIRST, gates[0]), _FakeProcess(SECOND, gates[1])])
    monkeypatch.setattr(shell_exec.subprocess, "Popen", lambda *a, **k: next(processes))
    manager = shell_exec.ShellManager(shell_encoding="utf-8")

    with secret_log_scope():
        remember_secret(FIRST)
        manager.exec_shell(["first-program"])
    gates[0].set()                      # the first program prints after its run ended
    _join_readers(manager)

    with secret_log_scope():            # a later, independent run drains the old queue
        remember_secret(SECOND)
        manager.exec_shell(["second-program"])
    gates[1].set()
    _join_readers(manager)
    manager.exit_program()              # drained outside any run

    final = log_text()
    assert FIRST not in final
    assert SECOND not in final
    for line in ("out token=***", "err token=***"):
        assert final.count(line) == 2


def test_a_held_mask_outlives_close_until_its_last_holder_releases_it():
    scope = SecretLogScope()
    scope.remember(FIRST)
    assert scope.retain() and scope.retain()
    scope.close()
    assert not scope.active
    assert scope.scrub(FIRST) == "***"
    scope.release()
    assert scope.scrub(FIRST) == "***"
    scope.release()
    assert scope.scrub(FIRST) == FIRST       # the values are gone
    assert not scope.retain()                # an ended run cannot be held again
