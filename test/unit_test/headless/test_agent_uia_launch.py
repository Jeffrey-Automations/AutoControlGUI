"""Verify owned-window binding with injected native facts and actual hidden protocol helpers."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.uia_channel import OwnedUiaChannel
from je_auto_control.utils.agent_runtime.uia_launch import OwnedUiaLauncher
from je_auto_control.utils.exception.control_signals import OperationCancelledError
from je_auto_control.utils.process_memory.models import FailureReason, MemoryObservationError
from je_auto_control.utils.process_memory.windows_window import WindowOwnerQuery
from headless.test_process_memory_launch import LaunchKernel, attest, pin
from headless.test_process_memory_windows import Function

CHALLENGE = bytes(range(16))
HELPER = Path(__file__).resolve().parents[2] / "fixtures" / "uia_startup_helper.py"


class WindowApi:
    def __init__(self):
        self.pid, self.thread = 42, 8
        self.GetWindowThreadProcessId = Function(self.query)
        self.children = ()
        self.EnumChildWindows = Function(self.enumerate)

    def enumerate(self, hwnd, callback, _value):
        assert hwnd == 101
        for child in self.children:
            if not callback(child, None):
                break
        return 1

    def query(self, hwnd, pid):
        assert hwnd == 101
        pid._obj.value = self.pid
        return self.thread


class Channel:
    def __init__(self):
        self._process = SimpleNamespace(pid=42, _handle=77)
        self.retired, self.fail_close, self.invalid = False, False, False
        self.closed = 0
        self.value = {"fixture": "uia", "version": 1, "pid": 42, "hwnd": 101,
                      "challenge": CHALLENGE.hex()}

    def bootstrap(self, challenge, *, timeout, check):
        assert challenge == CHALLENGE and timeout == 5
        check()
        return self.value

    def check_live(self):
        if self.retired or self.invalid:
            raise AgentTaskError("invalid channel")

    def close(self):
        self.closed += 1
        if self.fail_close:
            raise AgentTaskError("retirement pending")
        self.retired = True


def setup():
    kernel, api, channel = LaunchKernel(), WindowApi(), Channel()
    calls = []
    def factory(argv):
        assert kernel.CreateFileW.calls
        calls.append(tuple(argv))
        return channel
    launcher = OwnedUiaLauncher(CHALLENGE, windows=WindowOwnerQuery(api), kernel=kernel,
        last_error=lambda: kernel.error, caller_bits=64, channel_factory=factory)
    return kernel, api, channel, calls, launcher


def test_binding_rechecks_retained_launch_and_window_without_opening_bootstrap_pid():
    kernel, api, channel, calls, launcher = setup()
    launch, *_ = attest(kernel, launcher=launcher)
    try:
        opened = list(kernel.OpenProcess.calls)
        measurements = len(kernel.GetProcessTimes.calls)
        bound = launcher.bind_window(launch, checkpoint=lambda: None)
        bound.verify(lambda: None)
        assert bound.identity == launch.identity and bound.hwnd == 101
        assert kernel.OpenProcess.calls == opened
        assert calls == [(kernel.image_path, "--challenge", CHALLENGE.hex())]
        assert all(call[0] == 77 for call in kernel.GetProcessTimes.calls[measurements:])
        assert len(api.GetWindowThreadProcessId.calls) == 4
        assert "101" not in repr(bound)
    finally:
        launcher.close()
        launch.close()
    assert channel.retired


@pytest.mark.parametrize("change", [{"pid": 43}, {"pid": True}, {"hwnd": True}, {"hwnd": 0},
    {"hwnd": 2**64}, {"version": True}, {"fixture": "memory"}, {"challenge": "wrong"},
    {"challenge": "\ud800"}, {"extra": 0}])
def test_invalid_bootstrap_retires_before_window_query(change):
    kernel, api, channel, _, launcher = setup()
    launch, *_ = attest(kernel, launcher=launcher)
    channel.value.update(change)
    try:
        with pytest.raises((AgentTaskError, MemoryObservationError)):
            launcher.bind_window(launch, checkpoint=lambda: None)
        assert channel.retired and not api.GetWindowThreadProcessId.calls
    finally:
        launcher.close()
        launch.close()


@pytest.mark.parametrize("fault", ["birth", "exit", "window_pid", "window_gone", "channel"])
def test_changed_lifetime_or_window_invalidates_existing_binding(fault):
    kernel, api, channel, _, launcher = setup()
    launch, *_ = attest(kernel, launcher=launcher)
    try:
        bound = launcher.bind_window(launch, checkpoint=lambda: None)
        if fault == "birth":
            kernel.birth += 1
        elif fault == "exit":
            kernel.wait = 0
        elif fault == "window_pid":
            api.pid = 43
        elif fault == "window_gone":
            api.thread = 0
        else:
            channel.invalid = True
        with pytest.raises((AgentTaskError, MemoryObservationError)):
            bound.verify(lambda: None)
        assert channel.retired
    finally:
        launcher.close()
        launch.close()


def test_checkpoint_revocation_retires_and_failed_cleanup_remains_retryable():
    kernel, _, channel, _, launcher = setup()
    launch, *_ = attest(kernel, launcher=launcher)
    try:
        bound = launcher.bind_window(launch, checkpoint=lambda: None)
        channel.fail_close = True
        def cancelled():
            raise OperationCancelledError("cancelled")
        with pytest.raises(OperationCancelledError) as error:
            bound.verify(cancelled)
        assert isinstance(error.value.__cause__, AgentTaskError) and not channel.retired
        channel.fail_close = False
        launcher.close()
        with pytest.raises(AgentTaskError):
            bound.verify(lambda: None)
    finally:
        channel.fail_close = False
        launcher.close()
        launch.close()


def test_wrong_pin_starts_no_channel():
    kernel, _, channel, calls, launcher = setup()
    with pytest.raises(MemoryObservationError):
        attest(kernel, launcher=launcher, pinned=pin(kernel, sha256="0" * 64))
    assert not calls and not channel.closed


@pytest.mark.parametrize("mode", ["valid", "wrong", "extra", "duplicate",
                                  "nested_duplicate", "oversize", "repeat", "wait"])
def test_hidden_helper_receive_only_protocol_and_retirement(mode):
    channel = OwnedUiaChannel([sys.executable, "-u", str(HELPER), CHALLENGE.hex(), mode])
    try:
        if mode == "valid":
            value = channel.bootstrap(CHALLENGE, timeout=2, check=lambda: None)
            assert value["hwnd"] == 101 and value["pid"] > 0
            with pytest.raises(AgentTaskError, match="receive-only"):
                channel.request("anything", {}, timeout=1)
            with pytest.raises(AgentTaskError, match="already consumed"):
                channel.bootstrap(CHALLENGE, timeout=1, check=lambda: None)
        else:
            if mode == "repeat":
                assert channel._invalid.wait(2)
            with pytest.raises(AgentTaskError):
                channel.bootstrap(CHALLENGE, timeout=0.2 if mode == "wait" else 2, check=lambda: None)
            assert channel.retired
    finally:
        channel.close()
    assert channel.retired


def test_close_interrupts_startup_wait_without_waiting_for_admission_lock():
    channel = OwnedUiaChannel([sys.executable, "-u", str(HELPER), CHALLENGE.hex(), "wait"])
    entered, done = threading.Event(), threading.Event()
    errors = []
    def capture():
        try:
            channel.bootstrap(CHALLENGE, timeout=10, check=entered.set)
        except AgentTaskError as error:
            errors.append(error)
        finally:
            done.set()
    worker = threading.Thread(target=capture)
    worker.start()
    try:
        assert entered.wait(2)
        channel.close()
        assert done.wait(2) and errors and channel.retired
    finally:
        channel.close()
        worker.join(2)


@pytest.mark.parametrize("boundary", ["window", "process"])
def test_revocation_during_final_native_checks_prevents_publication(boundary):
    kernel, api, channel, _, launcher = setup()
    launch, *_ = attest(kernel, launcher=launcher)
    revoked = False
    checks = 0
    def checkpoint():
        if revoked:
            raise OperationCancelledError("revoked during query")
    try:
        if boundary == "window":
            original = api.query
            def query(*args):
                nonlocal revoked, checks
                result = original(*args)
                checks += 1
                if checks == 2:
                    revoked = True
                return result
            api.GetWindowThreadProcessId = Function(query)
        else:
            original = launcher._launcher.facts
            def facts():
                nonlocal revoked, checks
                result = original()
                checks += 1
                if checks == 4:
                    revoked = True
                return result
            launcher._launcher.facts = facts
        with pytest.raises(OperationCancelledError):
            launcher.bind_window(launch, checkpoint=checkpoint)
        assert channel.retired and launcher._binding is None
    finally:
        launcher.close()
        launch.close()


def test_close_reentered_from_bootstrap_checkpoint_cannot_publish():
    kernel, _, channel, _, launcher = setup()
    launch, *_ = attest(kernel, launcher=launcher)
    checks = 0
    def checkpoint():
        nonlocal checks
        checks += 1
        if checks == 2:
            launcher.close()
    try:
        with pytest.raises(AgentTaskError):
            launcher.bind_window(launch, checkpoint=checkpoint)
        assert channel.retired and launcher._binding is None
    finally:
        launcher.close()
        launch.close()


def test_the_binding_lists_current_child_windows_only_while_its_window_lives():
    _, api, _, _, launcher = setup()
    query = WindowOwnerQuery(api)
    api.children = (201, 202)
    assert query.children(101) == (201, 202)
    api.thread = 0
    with pytest.raises(MemoryObservationError):
        query.children(101)
    launcher.close()


def test_too_many_child_windows_are_refused_instead_of_truncated():
    _, api, _, _, launcher = setup()
    api.children = tuple(range(1, 4099))
    with pytest.raises(MemoryObservationError) as error:
        WindowOwnerQuery(api).children(101)
    assert error.value.reason is FailureReason.BUDGET_EXCEEDED
    launcher.close()
