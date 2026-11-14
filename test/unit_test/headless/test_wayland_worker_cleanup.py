"""Owned EI protocol and process retirement with synthetic backends only."""
import io
from concurrent.futures import CancelledError
import json
from pathlib import Path
import sys
import threading
import time

import pytest

from je_auto_control.linux_wayland.ei_protocol import EiProtocolError, InputEvent, MAX_EVENTS, MAX_PACKET, encode
from je_auto_control.linux_wayland.ei_transport import EiWorkerClient
from je_auto_control.linux_wayland.ei_worker import EiWorker
from je_auto_control.linux_wayland.libei import LibeiUnavailable
from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope


@pytest.fixture
def default_cache(monkeypatch):
    from je_auto_control.linux_wayland import ei_default
    ei_default.reset_default_backend()
    proxy, channel = client()
    monkeypatch.setattr(ei_default, '_new_default_backend', lambda: proxy)
    yield ei_default, proxy, channel
    channel.fail_close = False
    ei_default.reset_default_backend()


def test_default_probe_has_no_consent_and_connect_reuses_owner(default_cache):
    cache, proxy, channel = default_cache
    assert cache.get_default_backend() is proxy
    assert channel.calls == ['probe']
    assert channel.backend.calls == []
    assert cache.connected_backend() is proxy
    assert cache.connected_backend() is proxy
    assert channel.calls == ['probe', 'connect']


def test_default_refusal_is_cached_without_new_worker_or_fallback(default_cache):
    cache, proxy, channel = default_cache
    channel.backend.failure = LibeiUnavailable('refused', state='needs_permission')
    with pytest.raises(LibeiUnavailable):
        cache.connected_backend()
    calls = list(channel.calls)
    with pytest.raises(LibeiUnavailable) as caught:
        cache.get_default_backend()
    assert caught.value.state == 'needs_permission'
    assert channel.calls == calls
    assert proxy.retired


def test_default_failed_close_retains_owner_for_explicit_retry(default_cache):
    cache, proxy, channel = default_cache
    cache.connected_backend()
    channel.fail_close = True
    with pytest.raises(EiProtocolError):
        cache.reset_default_backend()
    assert cache._DEFAULT_BACKEND is proxy
    assert not proxy.retired
    channel.fail_close = False
    cache.reset_default_backend()
    assert proxy.retired and cache._DEFAULT_BACKEND is None


def test_default_optional_absence_is_probed_once(default_cache):
    cache, proxy, channel = default_cache
    channel.backend.is_available = False
    assert cache.get_default_backend() is None
    assert cache.get_default_backend() is None
    assert channel.calls == ['probe', 'disconnect']
    assert proxy.retired


class Backend:
    is_available = True
    is_connected = False

    def __init__(self):
        self.calls = []
        self.failure = None

    def observed_state(self):
        return "available" if self.is_connected else "unverified"

    def connect(self, **kwargs):
        self.calls.append(("connect", kwargs))
        if self.failure:
            raise self.failure
        self.is_connected = True

    def disconnect(self):
        self.calls.append(("disconnect",))
        self.is_connected = False

    def __getattr__(self, name):
        def emit(*values):
            self.calls.append((name, *values))
            if self.failure:
                raise self.failure
        return emit


class Channel:
    retired = False

    def __init__(self, backend=None):
        self.backend = backend or Backend()
        self.worker = EiWorker(lambda: self.backend)
        self.calls = []
        self.fail_close = False
        self.change_reply = lambda reply: reply

    def request(self, operation, payload, *, timeout, check):
        check()
        self.calls.append(operation)
        reply, _ = self.worker.handle({"id": "request", "operation": operation, "payload": payload})
        return self.change_reply(reply["result"])

    def close(self):
        if not self.fail_close:
            self.retired = True


def client(backend=None):
    channel = Channel(backend)
    return EiWorkerClient(factory=lambda: channel), channel


def envelope(operation, arguments, sequence=1):
    return {"id": "request", "operation": operation,
            "payload": {"version": 1, "sequence": sequence, "arguments": arguments}}


def test_probe_is_passive_and_graceful_close_releases_owned_keys_and_buttons():
    proxy, channel = client()
    assert proxy.is_available and not proxy.is_connected
    assert channel.backend.calls == []
    proxy.connect()
    proxy.press_key(28)
    proxy.press_button(272)
    assert proxy.observed_state() == "available"
    proxy.disconnect()
    assert ("release_key", 28) in channel.backend.calls
    assert ("release_button", 272) in channel.backend.calls
    assert proxy.retired and proxy.cleanup_confirmed
    with pytest.raises(LibeiUnavailable):
        proxy.send((InputEvent("press_key", (28,)),))


@pytest.mark.parametrize("kind,args", [("shell", (1,)), ("press_key", (True,)), ("press_key", (-1,)),
                                       ("scroll", (1,)), ("set_position", (1.5, 2))])
def test_invalid_event_rejected_before_native_or_worker_creation(kind, args):
    with pytest.raises(EiProtocolError):
        InputEvent(kind, args)


def test_entire_batch_is_validated_before_emission():
    backend = Backend()
    worker = EiWorker(lambda: backend)
    events = [InputEvent("press_key", (28,)).wire(), {"kind": "press_key", "arguments": [True]}]
    reply, _ = worker.handle(envelope("send", {"events": events}))
    assert not reply["result"]["ok"] and backend.calls == []
    proxy, channel = client()
    with pytest.raises(EiProtocolError):
        proxy.send((InputEvent("press_key", (28,)),) * (MAX_EVENTS + 1))
    assert channel.calls == []


@pytest.mark.parametrize("state,fallback", [("unavailable", True), ("needs_permission", False),
                                          ("revoked", False), ("paused", False)])
def test_connect_preserves_authority_failure_and_never_retries(state, fallback):
    backend = Backend()
    backend.failure = LibeiUnavailable("private native message", state=state)
    proxy, channel = client(backend)
    for _ in range(2):
        with pytest.raises(LibeiUnavailable) as caught:
            proxy.connect()
        assert caught.value.status.fallback_allowed is fallback
        assert caught.value.state == state
        assert "private" not in str(caught.value)
    assert channel.calls == ["connect"] and proxy.retired


def test_failed_send_is_uncertain_and_cannot_enable_optional_fallback():
    proxy, channel = client()
    proxy.connect()
    channel.backend.failure = LibeiUnavailable("unknown emission")
    with pytest.raises(LibeiUnavailable) as caught:
        proxy.press_key(28)
    assert not caught.value.status.fallback_allowed
    with pytest.raises(LibeiUnavailable):
        proxy.press_key(28)
    assert channel.calls == ["connect", "send"]


@pytest.mark.parametrize("change", [
    lambda reply: {**reply, "sequence": 0},
    lambda reply: {**reply, "version": True},
    lambda reply: {**reply, "foreign": 1},
])
def test_malformed_reply_retires_and_latches_no_replay(change):
    proxy, channel = client()
    channel.change_reply = change
    with pytest.raises(LibeiUnavailable):
        proxy.connect()
    with pytest.raises(LibeiUnavailable):
        proxy.connect()
    assert channel.calls == ["connect"] and proxy.retired


def test_partial_acknowledgement_is_not_success():
    proxy, channel = client()
    channel.change_reply = lambda reply: {**reply, "value": {**reply["value"], "emitted": 0}}
    with pytest.raises(LibeiUnavailable):
        proxy.send((InputEvent("press_key", (28,)),))
    assert proxy.retired and not proxy.cleanup_confirmed


@pytest.mark.parametrize('emitted', [0, True, '1'])
def test_bad_ack_retires_before_a_queued_send_can_emit(monkeypatch, emitted):
    proxy, channel = client()
    retiring, release_retirement, second_queued = threading.Event(), threading.Event(), threading.Event()
    errors = []
    admission = []
    original_retire, original_acquire = proxy._retire_failed, proxy._acquire

    def retire(error):
        retiring.set()
        assert release_retirement.wait(2)
        original_retire(error)

    def acquire(deadline):
        if retiring.is_set():
            available = proxy._request_lock.acquire(blocking=False)
            admission.append(available)
            if available:
                proxy._request_lock.release()
            second_queued.set()
        original_acquire(deadline)

    def send(code):
        try:
            proxy.press_key(code)
        except LibeiUnavailable as error:
            errors.append(error)

    def reply(value):
        if len(channel.calls) == 1:
            return {**value, 'value': {**value['value'], 'emitted': emitted}}
        return value

    monkeypatch.setattr(proxy, '_retire_failed', retire)
    monkeypatch.setattr(proxy, '_acquire', acquire)
    channel.change_reply = reply
    first, second = threading.Thread(target=send, args=(28,)), threading.Thread(target=send, args=(29,))
    first.start()
    try:
        assert retiring.wait(2)
        second.start()
        assert second_queued.wait(2)
        assert admission == [False]
        assert ('press_key', 29) not in channel.backend.calls
    finally:
        release_retirement.set()
        first.join(2)
        if second.ident is not None:
            second.join(2)
        proxy.disconnect()
    assert not first.is_alive() and not second.is_alive()
    assert len(errors) == 2
    assert channel.calls == ['send'] and proxy.retired


def test_failed_close_retains_owner_for_retry():
    proxy, channel = client()
    proxy.connect()
    channel.fail_close = True
    with pytest.raises(EiProtocolError, match="retirement"):
        proxy.disconnect()
    assert not proxy.retired
    channel.fail_close = False
    proxy.disconnect()
    assert proxy.retired


def test_cancellation_after_native_call_retires_and_preserves_signal():
    proxy, channel = client()
    token = CancellationToken("ei-test")
    original = channel.request

    def cancel(*args, **kwargs):
        result = original(*args, **kwargs)
        token.cancel()
        return result

    channel.request = cancel
    with cancellation_scope(token), pytest.raises(Exception) as caught:
        proxy.connect()
    assert type(caught.value).__name__ == "CancelledError"
    assert proxy.retired


def test_queue_time_is_inside_deadline_without_retiring_another_request():
    proxy, channel = client()
    proxy._request_lock.acquire()
    start = time.monotonic()
    try:
        with pytest.raises(EiProtocolError, match="queue deadline"):
            proxy.send((InputEvent("press_key", (28,)),), timeout_s=0.02)
    finally:
        proxy._request_lock.release()
    assert time.monotonic() - start < 0.5
    assert channel.calls == []


def test_close_during_startup_keeps_late_handle_owned():
    entered, release = threading.Event(), threading.Event()
    channel = Channel()

    def factory():
        entered.set()
        assert release.wait(2)
        return channel

    proxy = EiWorkerClient(factory=factory)
    errors = []

    def connect():
        try:
            proxy.connect()
        except LibeiUnavailable as error:
            errors.append(error)

    thread = threading.Thread(target=connect)
    thread.start()
    try:
        assert entered.wait(2)
        with pytest.raises(EiProtocolError, match="startup retirement"):
            proxy.close()
        assert not proxy.retired
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive() and errors and proxy.retired and channel.calls == []


def test_duplicate_sequence_and_oversized_frames_do_not_emit():
    backend = Backend()
    worker = EiWorker(lambda: backend)
    request = envelope("send", {"events": [InputEvent("press_key", (28,)).wire()]})
    worker.handle(request)
    with pytest.raises(EiProtocolError):
        worker.handle(request)
    assert backend.calls == [("press_key", 28)]
    sink = io.BytesIO()
    worker.run(io.BytesIO(b"x" * (MAX_PACKET + 1)), sink)
    assert sink.getvalue() == b""
    assert ("release_key", 28) in backend.calls


def test_synthetic_owned_child_uses_real_ipc_and_retires_without_touching_native():
    from je_auto_control.utils.agent_runtime.native_channel import OwnedChannel
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "ei_worker_fixture.py"
    channels = []

    def factory():
        channel = OwnedChannel([sys.executable, "-u", str(fixture)])
        channels.append(channel)
        return channel

    left, right = EiWorkerClient(factory=factory), EiWorkerClient(factory=factory)
    try:
        left.connect()
        right.connect()
        assert left.send((InputEvent("press_key", (28,)),)).emitted == 1
        left.close()
        assert left.retired and left.cleanup_confirmed
        assert right.send((InputEvent("set_position", (10, 20)),)).emitted == 1
        assert not right.retired
    finally:
        left.close()
        right.close()
    assert right.retired and all(channel.retired for channel in channels)


def test_eof_releases_ledger_and_emits_bounded_reply():
    backend = Backend()
    source = io.BytesIO(encode(envelope("send", {"events": [InputEvent("press_key", (28,)).wire()]})))
    sink = io.BytesIO()
    EiWorker(lambda: backend).run(source, sink)
    assert json.loads(sink.getvalue())["result"]["value"]["emitted"] == 1
    assert backend.calls[-2:] == [("release_key", 28), ("disconnect",)]


@pytest.mark.parametrize('code', [998, 999])
def test_real_child_lost_or_stalled_reply_retires_without_replay(code):
    from je_auto_control.utils.agent_runtime.native_channel import OwnedChannel
    fixture = Path(__file__).resolve().parents[2] / 'fixtures' / 'ei_worker_fixture.py'
    channels = []

    def factory():
        channel = OwnedChannel([sys.executable, '-u', str(fixture)])
        channels.append(channel)
        return channel

    proxy = EiWorkerClient(factory=factory)
    try:
        proxy.connect()
        with pytest.raises(LibeiUnavailable) as caught:
            proxy.send((InputEvent('press_key', (code,)),), timeout_s=0.15)
        assert not caught.value.status.fallback_allowed
        assert proxy.retired
        with pytest.raises(LibeiUnavailable):
            proxy.press_key(28)
        assert len(channels) == 1
    finally:
        proxy.disconnect()


def test_cleanup_attempts_every_release_even_when_one_fails():
    backend = Backend()
    worker = EiWorker(lambda: backend)
    worker.handle(envelope('send', {'events': [InputEvent('press_key', (28,)).wire(),
                                             InputEvent('press_button', (272,)).wire()]}))
    backend.failure = RuntimeError('release refused')
    assert not worker.close()
    assert ('release_key', 28) in backend.calls
    assert ('release_button', 272) in backend.calls
    assert ('disconnect',) in backend.calls


def test_cancelling_real_stalled_child_preserves_control_and_reaps():
    from je_auto_control.utils.agent_runtime.native_channel import OwnedChannel
    fixture = Path(__file__).resolve().parents[2] / 'fixtures' / 'ei_worker_fixture.py'
    proxy = EiWorkerClient(factory=lambda: OwnedChannel([sys.executable, '-u', str(fixture)]))
    token = CancellationToken('ei-real-cancel')
    timer = threading.Timer(0.15, token.cancel)
    try:
        proxy.connect()
        timer.start()
        with cancellation_scope(token), pytest.raises(CancelledError):
            proxy.send((InputEvent('press_key', (998,)),), timeout_s=2)
        assert proxy.retired
    finally:
        timer.cancel()
        timer.join()
        proxy.disconnect()
