"""Host side of the Android device helper: transport, client, physical source and provider. No device, no Qt."""
from __future__ import annotations

import json
import socket
import struct
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from je_auto_control.utils.agent_runtime import android_adapter
from je_auto_control.utils.agent_runtime.android_action_result import AndroidActionResult
from je_auto_control.utils.agent_runtime.android_getevent import GETEVENT_COMMAND, GeteventSource
from je_auto_control.utils.agent_runtime.android_helper_client import (
    HELPER_SOCKET, KEYCODES, AndroidHelperClient, helper_command,
)
from je_auto_control.utils.agent_runtime.android_helper_provider import HelperControlProvider
from je_auto_control.utils.agent_runtime.errors import AgentControlBusy, AgentTaskError

from .test_agent_android_transport import packet, read_exact, request, server

BOOT = "0f0e0d0c-0b0a-0908-0706-050403020100"
ID = "a" * 32


# --- transport --------------------------------------------------------------------------------

def test_one_line_is_exchanged_with_a_device_abstract_socket():
    def dialogue(connection):
        assert request(connection) == b"host:transport-id:42"
        connection.sendall(b"OKAY")
        assert request(connection) == b"localabstract:" + HELPER_SOCKET.encode()
        connection.sendall(b"OKAY")
        assert read_exact(connection, len(b'{"op":"hello"}\n')) == b'{"op":"hello"}\n'
        connection.sendall(b'{"a":1}\nlate')
    with server(dialogue) as (adb, _connections):
        assert adb.exchange_local(42, HELPER_SOCKET, b'{"op":"hello"}\n', timeout=2) == b'{"a":1}\n'


@pytest.mark.parametrize("name, line", [("Bad-Name", b"x\n"), (HELPER_SOCKET, b"x"), (HELPER_SOCKET, b"a\nb\n"),
                                        (HELPER_SOCKET, b"")])
def test_malformed_local_requests_never_open_a_connection(name, line, monkeypatch):
    from je_auto_control.utils.agent_runtime.android_transport import ManagedAdbServer
    adb = ManagedAdbServer("127.0.0.1", 9)
    monkeypatch.setattr(adb, "_connect", lambda *_a: pytest.fail("connected"))
    with pytest.raises(AgentTaskError):
        adb.exchange_local(42, name, line, timeout=1)


def test_an_unterminated_or_oversized_reply_is_refused():
    def dialogue(connection):
        request(connection), connection.sendall(b"OKAY"), request(connection), connection.sendall(b"OKAY")
        read_exact(connection, 2)
        connection.sendall(b"x" * 64)
    with server(dialogue) as (adb, _connections):
        with pytest.raises(AgentTaskError, match="byte limit"):
            adb.exchange_local(42, HELPER_SOCKET, b"{\n", timeout=2, limit=16)


def test_a_long_lived_shell_stream_is_handed_to_its_owner():
    def dialogue(connection):
        assert request(connection) == b"host:transport-id:7"
        connection.sendall(b"OKAY")
        assert request(connection) == b"shell,v2,raw:" + GETEVENT_COMMAND.encode()
        connection.sendall(b"OKAY")
        assert read_exact(connection, 5) == packet(4, b"")
        connection.sendall(packet(1, b"/dev/input/event1: EV_KEY KEY_POWER DOWN\n"))
    with server(dialogue) as (adb, _connections):
        stream = adb.open_shell_stream(7, GETEVENT_COMMAND, timeout=2)
        try:
            stream.settimeout(2)
            assert read_exact(stream, 5) == struct.pack("<BI", 1, 41)
        finally:
            stream.close()


# --- client -----------------------------------------------------------------------------------

class Exchange:
    def __init__(self, *replies):
        self.replies, self.sent = list(replies), []

    def exchange_local(self, transport, name, line, *, timeout, check):
        assert (transport, name) == (5, HELPER_SOCKET) and line.endswith(b"\n")
        self.sent.append(json.loads(line))
        return (json.dumps(self.replies.pop(0)) + "\n").encode()


def client(*replies):
    exchange = Exchange(*replies)
    return AndroidHelperClient(exchange, lambda timeout, check: 5), exchange


def test_the_client_validates_every_closed_reply():
    helper, exchange = client(
        {"protocol": 1, "boot_id": BOOT, "helper_epoch": "1" * 32, "epoch": "1" * 32},
        {"epoch": "2" * 32, "fenced": [ID], "inflight": None, "queue_empty": True},
        {"id": ID, "accepted": False, "reason": "stale_epoch"},
        {"id": ID, "boot_id": BOOT, "epoch": "2" * 32, "status": "fenced", "input_released": True,
         "queue_empty": True})
    assert helper.hello(timeout=1, check=lambda: None).helper_epoch == "1" * 32
    assert helper.fence("2" * 32, timeout=1, check=lambda: None).fenced == (ID,)
    assert helper.begin(ID, "2" * 32, {"kind": "tap", "x": 1, "y": 2}, timeout=1, check=lambda: None) == (
        False, "stale_epoch")
    assert helper.settle(ID, timeout=1, check=lambda: None).status == "fenced"
    assert [item["op"] for item in exchange.sent] == ["hello", "fence", "begin", "settle"]


@pytest.mark.parametrize("call, reply", [
    ("hello", {"error": "unknown_op"}),
    ("hello", {"protocol": 2, "boot_id": BOOT, "helper_epoch": "1" * 32, "epoch": "1" * 32}),
    ("fence", {"epoch": "3" * 32, "fenced": [], "inflight": None, "queue_empty": True}),
    ("fence", {"epoch": "2" * 32, "fenced": ["x"], "inflight": None, "queue_empty": True}),
    ("begin", {"id": "b" * 32, "accepted": True, "reason": None}),
    ("begin", {"id": ID, "accepted": "yes", "reason": None}),
    ("settle", {"id": ID, "boot_id": BOOT, "epoch": "2" * 32, "status": "done", "input_released": True,
                "queue_empty": True}),
    ("settle", {"id": ID, "boot_id": BOOT, "epoch": "2" * 32, "status": "completed", "input_released": 1,
                "queue_empty": True}),
])
def test_unexpected_helper_replies_are_refused(call, reply):
    helper, _exchange = client(reply)
    calls = {"hello": lambda: helper.hello(timeout=1, check=lambda: None),
             "fence": lambda: helper.fence("2" * 32, timeout=1, check=lambda: None),
             "begin": lambda: helper.begin(ID, "2" * 32, {}, timeout=1, check=lambda: None),
             "settle": lambda: helper.settle(ID, timeout=1, check=lambda: None)}
    with pytest.raises(AgentTaskError):
        calls[call]()


def test_tool_calls_map_to_the_helpers_closed_commands():
    assert helper_command("AC_android_tap", {"x": 3, "y": 4}) == {"kind": "tap", "x": 3, "y": 4}
    assert helper_command("AC_android_swipe", {"x1": 1, "y1": 2, "x2": 3, "y2": 4}) == {
        "kind": "swipe", "x": 1, "y": 2, "to_x": 3, "to_y": 4, "duration_ms": 250}
    assert helper_command("AC_android_key", {"key": "KEYCODE_BACK"}) == {"kind": "key", "keycode": 4}
    assert KEYCODES["ENTER"] == 66
    with pytest.raises(AgentTaskError, match="text input"):
        helper_command("AC_android_text", {"text": "hi"})


# --- physical source --------------------------------------------------------------------------

@contextmanager
def getevent(clock):
    near, far = socket.socketpair()
    source = GeteventSource(lambda: near, clock=clock)
    notified = threading.Event()
    source.set_handler(notified.set)
    source.start()
    try:
        yield source, far, notified
    finally:
        source.close()
        far.close()


def test_physical_events_mark_activity_and_notify_the_handler():
    now = [100.0]
    with getevent(lambda: now[0]) as (source, far, notified):
        now[0] = 160.0
        assert source.healthy and source.idle_for() == 60.0
        far.sendall(packet(1, b"add device 1: /dev/input/event1\n  name: \"gpio-keys\"\n"))
        far.sendall(packet(1, b"/dev/input/event1: EV_KEY       KEY_VOLUMEDOWN       DO"))
        assert not notified.wait(0.3)
        far.sendall(packet(1, b"WN\n"))
        assert notified.wait(2)
        assert source.idle_for() == 0.0


def test_an_ended_or_malformed_stream_makes_the_source_unhealthy():
    with getevent(time.monotonic) as (source, far, notified):
        far.sendall(packet(3, b"\0"))
        assert notified.wait(2)
        deadline = time.monotonic() + 2
        while source.healthy and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not source.healthy and source.idle_for() == 0.0


# --- provider ---------------------------------------------------------------------------------

class Helper:
    """A Python port of the helper's FenceLedger semantics behind the client's interface."""

    def __init__(self):
        self.boot, self.helper_epoch, self.epoch = BOOT, "1" * 32, "1" * 32
        self.records, self.queue, self.injecting = {}, [], None
        self.fences, self.complete_after = [], 1

    def hello(self, *, timeout, check):
        return SimpleNamespace(boot_id=self.boot, helper_epoch=self.helper_epoch, epoch=self.epoch)

    def fence(self, epoch, *, timeout, check):
        assert epoch != self.epoch
        self.epoch = epoch
        self.fences.append(epoch)
        fenced = [rid for rid in self.queue if self.records[rid]["epoch"] != epoch]
        for rid in fenced:
            self.records[rid]["status"] = "fenced"
        self.queue = [rid for rid in self.queue if rid not in fenced]
        if self.injecting is not None and self.records[self.injecting]["epoch"] != epoch:
            self.records[self.injecting].update(status="fenced", released=True)
            self.injecting = None
        return SimpleNamespace(epoch=epoch, fenced=tuple(fenced), inflight=self.injecting,
                               queue_empty=not self.queue and self.injecting is None)

    def begin(self, request_id, epoch, command, *, timeout, check):
        if epoch != self.epoch or request_id in self.records:
            return False, "stale_epoch"
        self.records[request_id] = {"epoch": epoch, "status": "queued", "released": True, "polls": 0,
                                    "command": command}
        self.queue.append(request_id)
        return True, ""

    def settle(self, request_id, *, timeout, check):
        record = self.records.get(request_id)
        if record is None:
            return SimpleNamespace(boot_id=self.boot, epoch=self.epoch, status="rejected", input_released=True,
                                   queue_empty=True)
        if record["status"] == "queued" and request_id in self.queue:
            self.queue.remove(request_id)
            record.update(status="injecting", released=False)
            self.injecting = request_id
        elif record["status"] == "injecting":
            record["polls"] += 1
            if record["polls"] >= self.complete_after:
                record.update(status="completed", released=True)
                self.injecting = None
        return SimpleNamespace(boot_id=self.boot, epoch=record["epoch"], status=record["status"],
                               input_released=record["released"],
                               queue_empty=not self.queue and self.injecting is None)


class Source:
    def __init__(self):
        self.healthy, self.idle, self.handler, self.closed = True, 120.0, None, False

    def set_handler(self, handler):
        self.handler = handler

    def idle_for(self):
        return self.idle

    def close(self):
        self.closed = True


def proposal():
    snapshot = SimpleNamespace(boot_id=BOOT, physical_id="reviewed-device")
    return SimpleNamespace(snapshot=snapshot, input_evidence=object())


@pytest.fixture
def provider(monkeypatch):
    from je_auto_control.utils.agent_runtime import android_control
    monkeypatch.setattr(android_control, "AndroidActionProposal", SimpleNamespace)
    helper, source = Helper(), Source()
    return HelperControlProvider(helper, source), helper, source


def ready(control):
    return control.ready(SimpleNamespace(boot_id=BOOT), None, None)


def test_readiness_needs_the_same_boot_and_a_quiet_healthy_source(provider):
    control, helper, source = provider
    assert ready(control) == (True, "")
    source.idle = 30.0
    assert ready(control) == (False, "Android physical input was active within the idle window")
    source.healthy = False
    assert ready(control)[0] is False
    helper.boot = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    assert ready(control) == (False, "Android helper runs on a different boot than the checked device")


def test_a_restarted_helper_makes_earlier_commands_unknown(provider):
    control, helper, _source = provider
    ready(control)
    helper.helper_epoch = "9" * 32
    with pytest.raises(AgentControlBusy, match="restarted"):
        ready(control)


def test_a_lease_runs_only_under_its_own_fresh_epoch_and_settles_through_the_helper(provider):
    control, helper, _source = provider
    ready(control)
    lease = control.lease(proposal(), ID)
    assert lease.epoch == helper.epoch == helper.fences[-1] and lease.dispatch is not None
    with lease.device_fence():
        result = lease.dispatch("AC_android_tap", {"x": 5, "y": 6}, time.monotonic() + 5, lambda: None)
    assert result == AndroidActionResult("input_returned", 0)
    assert helper.records[ID]["command"] == {"kind": "tap", "x": 5, "y": 6}
    assert lease.settle(result) == {"device": {"platform": "android", "physical_id": "reviewed-device"},
                                    "epoch": lease.epoch, "inputs_released": True, "queue_empty": True,
                                    "request_id": ID, "boot_id": BOOT}


def test_physical_input_fences_an_injecting_command_and_refuses_what_follows(provider):
    control, helper, source = provider
    taken = []
    control.set_takeover_handler(lambda: taken.append(True))
    ready(control)
    helper.complete_after = 10**6
    lease = control.lease(proposal(), ID)

    def check():
        if helper.injecting == ID and not taken:
            source.handler()  # a person touches the screen while the command is injecting

    result = lease.dispatch("AC_android_tap", {"x": 5, "y": 6}, time.monotonic() + 5, check)
    assert result.phase == "input_failed" and result.may_have_effect
    assert taken == [True] and helper.records[ID]["status"] == "fenced" and helper.epoch != lease.epoch
    with pytest.raises(AgentControlBusy, match="took over"):
        lease.checkpoint()
    with pytest.raises(AgentControlBusy):
        control.lease(proposal(), "b" * 32)


def test_an_error_inside_the_device_fence_fences_again(provider):
    control, helper, _source = provider
    ready(control)
    lease = control.lease(proposal(), ID)
    before = len(helper.fences)
    with pytest.raises(RuntimeError):
        with lease.device_fence():
            raise RuntimeError("dispatch failed")
    assert len(helper.fences) == before + 1


def test_a_refused_begin_is_a_proven_no_effect(provider):
    control, helper, _source = provider
    ready(control)
    lease = control.lease(proposal(), ID)
    helper.epoch = "f" * 32  # someone else fenced the device after the lease
    result = lease.dispatch("AC_android_key", {"key": "BACK"}, time.monotonic() + 5, lambda: None)
    assert result.phase == "pre_input_refused" and not result.may_have_effect


def test_a_command_that_does_not_settle_in_time_is_unknown(provider):
    control, helper, _source = provider
    ready(control)
    helper.complete_after = 10**6
    lease = control.lease(proposal(), ID)
    with pytest.raises(AgentTaskError, match="did not settle"):
        lease.dispatch("AC_android_tap", {"x": 1, "y": 1}, time.monotonic() + 0.2, lambda: None)


def test_a_lease_is_refused_while_an_earlier_write_is_still_in_progress(provider):
    control, helper, _source = provider
    ready(control)
    helper.injecting = "c" * 32
    helper.records["c" * 32] = {"epoch": helper.epoch + "x", "status": "injecting", "released": False}
    original = helper.fence

    def stuck(epoch, **kwargs):
        result = original(epoch, **kwargs)
        return SimpleNamespace(**{**vars(result), "inflight": "c" * 32, "queue_empty": False})
    helper.fence = stuck
    with pytest.raises(AgentTaskError, match="earlier write"):
        control.lease(proposal(), ID)


def test_close_fences_and_stops_the_source(provider):
    control, helper, source = provider
    before = len(helper.fences)
    control.close()
    assert len(helper.fences) == before + 1 and source.closed


def test_the_adapter_sends_a_helper_lease_through_its_device_writer_not_adb_input():
    sent = []
    lease = SimpleNamespace(
        proposal=SimpleNamespace(snapshot=SimpleNamespace(physical_id="reviewed-device")), epoch="e" * 32,
        request_id=ID, checkpoint=lambda: None, device_fence=contextmanager(lambda: (yield)),
        dispatch=lambda name, arguments, deadline, check: sent.append(name) or AndroidActionResult(
            "input_returned", 0), settle=lambda result: {})
    session = SimpleNamespace(dispatch_checked=lambda *a, **k: pytest.fail("adb input was used"))
    action = android_adapter._prepared_call(session, lease, "AC_android_tap", {"x": 1, "y": 2},
                                            time.monotonic() + 5, lambda: None, None)
    assert action.invoke() == {"android_phase": "input_returned", "may_have_effect": True}
    assert sent == ["AC_android_tap"]
