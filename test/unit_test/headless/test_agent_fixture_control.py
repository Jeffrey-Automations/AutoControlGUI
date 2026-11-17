"""Exercise owned fixture RPC in hidden children without native process memory reads."""
from asyncio import CancelledError
from pathlib import Path
import os
import sys

import pytest

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.fixture_control import OwnedFixtureControl
from je_auto_control.utils.agent_runtime.native_channel import OwnedChannel

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "process_memory_fixture.py"
CHALLENGE = bytes(range(1, 17))


def launch():
    channel = OwnedChannel([sys.executable, "-I", "-u", str(FIXTURE), "--rpc",
                            "--challenge", CHALLENGE.hex()])
    return channel, OwnedFixtureControl(channel, CHALLENGE)


def test_hidden_fixture_bootstrap_compare_set_replay_snapshot_and_retirement():
    channel, control = launch()
    try:
        session = control.bootstrap(timeout=1, checkpoint=lambda: None)
        assert session.binding.challenge == CHALLENGE
        assert session.binding.pid > 0 and session.binding.pid != os.getpid()
        request = {"command": "compare_set", "operation_id": "op-1",
                   "launch_nonce": session.launch_nonce, "expected_sequence": 0,
                   "document_id": 42, "job_status": "done"}
        first = control.request(request, timeout=1, checkpoint=lambda: None)
        assert first == control.request(request, timeout=1, checkpoint=lambda: None)
        state = control.request({"command": "snapshot"}, timeout=1, checkpoint=lambda: None)
        assert first["kind"] == "receipt" and first["sequence"] == 2
        assert state == {"kind": "snapshot", "sequence": 2, "document_id": 42, "job_status": "done"}
    finally:
        control.close()
    assert channel.retired and channel._process.returncode is not None
    with pytest.raises(AgentTaskError, match="retired"):
        control.bootstrap(timeout=1, checkpoint=lambda: None)


def test_unreviewed_set_is_refused_by_both_transport_and_rpc_server():
    channel, control = launch()
    try:
        control.bootstrap(timeout=1, checkpoint=lambda: None)
        request = {"command": "set", "document_id": 42, "job_status": "done"}
        with pytest.raises(AgentTaskError, match="unsupported"):
            control.request(request, timeout=1, checkpoint=lambda: None)
        assert channel.request("control", request, timeout=1) == {"kind": "error", "code": "invalid_request"}
        assert control.request({"command": "snapshot"}, timeout=1, checkpoint=lambda: None)["sequence"] == 0
    finally:
        control.close()


def test_timeout_reaps_hidden_child_and_prevents_reuse():
    channel = OwnedChannel([sys.executable, "-u", "-c", "import time; time.sleep(30)"])
    control = OwnedFixtureControl(channel, CHALLENGE)
    try:
        with pytest.raises(AgentTaskError, match="deadline"):
            control.bootstrap(timeout=0.1, checkpoint=lambda: None)
        assert channel.retired and channel._process.returncode is not None
        with pytest.raises(AgentTaskError, match="retired"):
            control.bootstrap(timeout=1, checkpoint=lambda: None)
    finally:
        control.close()


def test_async_cancellation_after_send_retires_actual_child():
    channel, control = launch()
    checks = 0

    def cancel():
        nonlocal checks
        checks += 1
        if checks >= 3:
            raise CancelledError()

    try:
        with pytest.raises(CancelledError):
            control.bootstrap(timeout=1, checkpoint=cancel)
        assert checks >= 3 and channel.retired and channel._process.returncode is not None
    finally:
        control.close()


class Channel:
    def __init__(self):
        self.retired = False
        self.closed = 0
        self.fail_close = False
        self.reply = {}

    def request(self, *_args, **_kwargs):
        return self.reply

    def close(self):
        self.closed += 1
        if self.fail_close:
            raise AgentTaskError("retirement pending")
        self.retired = True


def test_bad_bootstrap_keeps_failed_retirement_owned_for_retry():
    channel = Channel()
    control = OwnedFixtureControl(channel, CHALLENGE)
    channel.fail_close = True
    with pytest.raises(Exception):
        control.bootstrap(timeout=1, checkpoint=lambda: None)
    assert channel.closed == 1 and not channel.retired
    with pytest.raises(AgentTaskError, match="retired"):
        control.bootstrap(timeout=1, checkpoint=lambda: None)
    channel.fail_close = False
    control.close()
    assert channel.closed == 2 and channel.retired


def test_constructor_failure_does_not_take_channel_ownership():
    channel = Channel()
    with pytest.raises(AgentTaskError):
        OwnedFixtureControl(channel, bytes(16))
    assert channel.closed == 0


def test_close_interrupts_bootstrap_without_waiting_for_wrapper_lock():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    channel = OwnedChannel([sys.executable, "-u", "-c", "import time; time.sleep(30)"])
    control = OwnedFixtureControl(channel, CHALLENGE)
    entered = Event()
    checks = 0

    def checkpoint():
        nonlocal checks
        checks += 1
        if checks >= 3:
            entered.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(control.bootstrap, timeout=1, checkpoint=checkpoint)
        try:
            assert entered.wait(1)
            control.close()
            with pytest.raises(AgentTaskError):
                pending.result(timeout=2)
            assert channel.retired
        finally:
            control.close()


def test_malformed_control_result_retires_after_successful_exchange():
    channel, control = launch()
    try:
        control.bootstrap(timeout=1, checkpoint=lambda: None)
        channel.request = lambda *args, **kwargs: {"kind": "snapshot", "raw": "PRIVATE bytes"}
        with pytest.raises(AgentTaskError) as error:
            control.request({"command": "snapshot"}, timeout=1, checkpoint=lambda: None)
        assert "PRIVATE" not in str(error.value)
        assert channel.retired and channel._process.returncode is not None
    finally:
        control.close()


def test_oversized_frame_is_refused_before_exchange_and_keeps_owner_usable():
    channel, control = launch()
    try:
        control.bootstrap(timeout=1, checkpoint=lambda: None)
        with pytest.raises(AgentTaskError, match="frame"):
            control.request({"command": "compare_set", "extra": "x" * 1024},
                            timeout=1, checkpoint=lambda: None)
        assert not channel.retired
        assert control.request({"command": "snapshot"}, timeout=1, checkpoint=lambda: None)["sequence"] == 0
    finally:
        control.close()


def test_checkpoint_close_cannot_return_cached_bootstrap():
    channel, control = launch()
    try:
        control.bootstrap(timeout=1, checkpoint=lambda: None)
        with pytest.raises(AgentTaskError, match="retired"):
            control.bootstrap(timeout=1, checkpoint=control.close)
        assert channel.retired
    finally:
        control.close()
