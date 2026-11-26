"""Tests for the WebRTC usb-channel adapters (no aiortc needed).

A pair of LinkedChannels plus an immediate bridge gives a synchronous
loopback over the channel abstraction, so the host/client adapters are
exercised end to end exactly as they would be over a real DataChannel.
"""
import json
import threading
import time

import pytest

from je_auto_control.utils.usb.passthrough import (
    AclRule, Frame, Opcode, UsbAcl, UsbChannelClient, UsbChannelHost,
    UsbClientError, UsbPassthroughSession, decode_frame, encode_frame,
)
from je_auto_control.utils.usb.passthrough.backend import (
    BackendDevice, FakeUsbBackend,
)

_SAMPLE = BackendDevice(vendor_id="1050", product_id="0407", serial="ABC123")


class _ImmediateBridge:
    @staticmethod
    def call_soon(fn, *args):
        fn(*args)


class _LinkedChannel:
    """Fake RTCDataChannel whose ``send`` delivers to its peer's handler."""

    def __init__(self):
        self._peer = None
        self._handlers = {}

    def link(self, peer):
        self._peer = peer

    def on(self, event):
        def _register(fn):
            self._handlers[event] = fn
            return fn
        return _register

    def send(self, data):
        handler = self._peer._handlers.get("message")
        if handler is not None:
            handler(data)


def _linked_pair():
    host_ch, client_ch = _LinkedChannel(), _LinkedChannel()
    host_ch.link(client_ch)
    client_ch.link(host_ch)
    return host_ch, client_ch


def _wire(session, *, enabled=True):
    host_ch, client_ch = _linked_pair()
    host = UsbChannelHost(
        host_ch, session=session, bridge=_ImmediateBridge(),
        enabled_check=lambda: enabled,
    )
    client = UsbChannelClient(client_ch, bridge=_ImmediateBridge())
    return host, client


def _allow_acl(tmp_path, *devices):
    acl = UsbAcl(path=tmp_path / "acl.json")
    for dev in devices:
        acl.add_rule(AclRule(vendor_id=dev.vendor_id,
                             product_id=dev.product_id, allow=True))
    return acl


def test_channel_list_devices_round_trip(tmp_path):
    session = UsbPassthroughSession(
        FakeUsbBackend(devices=[_SAMPLE]), acl=_allow_acl(tmp_path, _SAMPLE),
    )
    _host, client = _wire(session)
    try:
        devices = client.list_devices()
        assert [d["vendor_id"] for d in devices] == ["1050"]
    finally:
        client.shutdown()


def test_channel_open_and_transfer(tmp_path):
    backend = FakeUsbBackend(devices=[_SAMPLE])
    session = UsbPassthroughSession(backend, acl=_allow_acl(tmp_path, _SAMPLE))
    _host, client = _wire(session)
    try:
        handle = client.open(vendor_id="1050", product_id="0407")
        backend_handle = next(iter(backend._open_handles.values()))
        backend_handle.transfer_hook = lambda kind, kwargs: b"\xaa\xbb"
        assert handle.control_transfer(
            bm_request_type=0xC0, b_request=6, length=2,
        ) == b"\xaa\xbb"
        assert handle.resume_token
    finally:
        client.shutdown()


def test_channel_resume_after_reconnect(tmp_path):
    backend = FakeUsbBackend(devices=[_SAMPLE])
    session = UsbPassthroughSession(backend, acl=_allow_acl(tmp_path, _SAMPLE))
    _host1, client1 = _wire(session)
    handle = client1.open(vendor_id="1050", product_id="0407")
    token = handle.resume_token
    client1.shutdown()  # transport drop; host keeps the claim
    assert session.active_claim_count == 1
    _host2, client2 = _wire(session)
    try:
        resumed = client2.resume(token)
        assert resumed.claim_id == handle.claim_id
    finally:
        client2.shutdown()


def test_channel_disabled_flag_rejects(tmp_path):
    session = UsbPassthroughSession(
        FakeUsbBackend(devices=[_SAMPLE]), acl=_allow_acl(tmp_path, _SAMPLE),
    )
    _host, client = _wire(session, enabled=False)
    try:
        with pytest.raises(UsbClientError):
            client.list_devices()
    finally:
        client.shutdown()


def test_host_lazy_session_factory(tmp_path):
    backend = FakeUsbBackend(devices=[_SAMPLE])
    built = []

    def factory():
        built.append(1)
        return UsbPassthroughSession(backend, acl=_allow_acl(tmp_path, _SAMPLE))

    host_ch, client_ch = _linked_pair()
    UsbChannelHost(host_ch, session_factory=factory,
                   bridge=_ImmediateBridge(), enabled_check=lambda: True)
    client = UsbChannelClient(client_ch, bridge=_ImmediateBridge())
    try:
        assert client.list_devices() == [
            {"vendor_id": "1050", "product_id": "0407",
             "serial": "ABC123", "bus_location": None},
        ]
        assert built == [1]  # session built lazily on first message
    finally:
        client.shutdown()


def test_host_rejects_non_binary_frame(tmp_path):
    session = UsbPassthroughSession(FakeUsbBackend(devices=[_SAMPLE]))
    host_ch, client_ch = _linked_pair()
    sent = []
    client_ch.on("message")(sent.append)
    UsbChannelHost(host_ch, session=session, bridge=_ImmediateBridge(),
                   enabled_check=lambda: True)
    # A str (not bytes) is invalid on the binary usb channel → ERROR back.
    host_ch._handlers["message"]("not-binary")
    assert len(sent) == 1
    reply = decode_frame(sent[0])
    assert reply.op == Opcode.ERROR


# --- concurrency: one blocked transfer must not freeze the event loop -------
#
# ``UsbChannelHost._on_message`` runs on the shared WebRTC event loop. A USB
# transfer may block for up to MAX_TIMEOUT_MS (60 s), so the host must only
# enqueue the frame there and serve it on the session's own worker.

_BLOCKING_EP = 0x81
_FREE_EP = 0x82
_PROMPT_S = 2.0      # "returned promptly": far below the blocked transfer
_WAIT_S = 5.0        # generous wait for a reply that should come


class _GatedBackend(FakeUsbBackend):
    """Bulk IN on endpoint 0x81 waits for ``gate``; every other transfer answers at once."""

    def __init__(self):
        super().__init__(devices=[_SAMPLE])
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.closes = 0

    def open(self, **kwargs):
        handle = super().open(**kwargs)
        handle.transfer_hook = self._hook
        real_close = handle.close

        def counting_close():
            self.closes += 1
            real_close()

        handle.close = counting_close
        return handle

    def _hook(self, _kind, kwargs):
        if kwargs.get("endpoint") == _BLOCKING_EP:
            self.entered.set()
            if not self.gate.wait(30):
                raise RuntimeError("gate never opened")
        return b"ok"


class _RecordingChannel:
    """Host-side fake channel: records every reply, thread-safely."""

    def __init__(self):
        self.handlers = {}
        self.frames = []
        self._cond = threading.Condition()

    def on(self, event):
        def _register(fn):
            self.handlers[event] = fn
            return fn
        return _register

    def send(self, data):
        with self._cond:
            self.frames.append(decode_frame(data))
            self._cond.notify_all()

    def deliver(self, frame):
        self.handlers["message"](encode_frame(frame))

    def wait_for(self, predicate, timeout=_WAIT_S):
        with self._cond:
            return self._cond.wait_for(lambda: predicate(list(self.frames)), timeout)

    def bodies(self, op):
        with self._cond:
            return [json.loads(f.payload) for f in self.frames if f.op == op]


def _returns_promptly(fn) -> bool:
    """Run ``fn`` as the event loop would; True if it returned within the bound."""
    thread = threading.Thread(target=fn, daemon=True)
    thread.start()
    thread.join(_PROMPT_S)
    return not thread.is_alive()


def _eventually(predicate) -> bool:
    deadline = time.monotonic() + _WAIT_S
    pause = threading.Event()
    while not predicate():
        if time.monotonic() > deadline:
            return False
        pause.wait(0.01)
    return True


def _host(backend, **kwargs):
    channel = _RecordingChannel()
    session = UsbPassthroughSession(backend)
    host = UsbChannelHost(channel, session=session, bridge=_ImmediateBridge(),
                          enabled_check=lambda: True, **kwargs)
    return host, channel, session


def _open_claim(channel) -> int:
    before = len(channel.bodies(Opcode.OPENED))
    channel.deliver(Frame(op=Opcode.OPEN, payload=json.dumps(
        {"vendor_id": "1050", "product_id": "0407"}).encode("utf-8")))
    assert channel.wait_for(lambda frames: len(
        [f for f in frames if f.op == Opcode.OPENED]) > before)
    body = channel.bodies(Opcode.OPENED)[-1]
    assert body["ok"], body
    return body["claim_id"]


def _bulk(claim_id, request_id, endpoint=_FREE_EP):
    return Frame(op=Opcode.BULK, claim_id=claim_id, payload=json.dumps({
        "endpoint": endpoint, "direction": "in", "length": 2,
        "request_id": request_id}).encode("utf-8"))


def _answered(channel, request_id) -> bool:
    return channel.wait_for(lambda frames: any(
        f.op in (Opcode.BULK, Opcode.ERROR)
        and json.loads(f.payload).get("request_id") == request_id for f in frames))


def _block(channel, backend, claim_id):
    """Start a transfer on ``claim_id`` that sits in the backend until ``gate``."""
    assert _returns_promptly(lambda: channel.deliver(_bulk(claim_id, "stuck", _BLOCKING_EP)))
    assert backend.entered.wait(_WAIT_S)


def test_blocked_transfer_does_not_stall_the_loop_or_another_session():
    backend_a, backend_b = _GatedBackend(), _GatedBackend()
    host_a, channel_a, _ = _host(backend_a)
    host_b, channel_b, _ = _host(backend_b)
    try:
        _block(channel_a, backend_a, _open_claim(channel_a))
        claim_b = _open_claim(channel_b)        # another session, served meanwhile
        assert _returns_promptly(lambda: channel_b.deliver(_bulk(claim_b, "b-1")))
        assert _answered(channel_b, "b-1")
    finally:
        backend_a.gate.set()
        host_a.close()
        host_b.close()


def test_another_claim_of_the_same_session_is_answered_while_one_blocks():
    backend = _GatedBackend()
    host, channel, _ = _host(backend)
    try:
        first, second = _open_claim(channel), _open_claim(channel)
        _block(channel, backend, first)
        assert _returns_promptly(lambda: channel.deliver(_bulk(second, "other-claim")))
        assert _answered(channel, "other-claim")
        assert not any(b.get("request_id") == "stuck" for b in channel.bodies(Opcode.BULK))
    finally:
        backend.gate.set()
        host.close()


def test_frames_of_one_claim_are_answered_in_order():
    backend = _GatedBackend()
    host, channel, _ = _host(backend)
    try:
        claim = _open_claim(channel)
        _block(channel, backend, claim)
        later = [f"r{n}" for n in range(6)]
        assert _returns_promptly(lambda: [channel.deliver(_bulk(claim, rid)) for rid in later])
        backend.gate.set()
        assert _answered(channel, later[-1])
        order = [b["request_id"] for b in channel.bodies(Opcode.BULK)]
        assert order == ["stuck", *later]
    finally:
        backend.gate.set()
        host.close()


def _limits(**kwargs):
    from je_auto_control.utils.usb.passthrough.session_worker import WorkerLimits
    return WorkerLimits(**kwargs)


def test_close_during_a_blocked_transfer_is_bounded_and_releases_every_claim():
    backend = _GatedBackend()
    host, channel, session = _host(backend, limits=_limits(join_timeout_s=0.2))
    try:
        stuck, idle = _open_claim(channel), _open_claim(channel)
        assert stuck != idle
        _block(channel, backend, stuck)
        assert _returns_promptly(host.close)
        assert session.active_claim_count == 0
        assert backend.open_handle_count == 1   # the busy handle waits for its transfer
        sent = len(channel.frames)
        backend.gate.set()
        assert _eventually(lambda: backend.open_handle_count == 0)
        assert backend.closes == 2              # each claim released exactly once
        assert len(channel.frames) == sent      # the late result was discarded
        host.close()                            # a second close releases nothing twice
        assert backend.closes == 2
    finally:
        backend.gate.set()
        host.close()


def test_the_per_session_queue_is_bounded():
    backend = _GatedBackend()
    host, channel, _ = _host(backend, limits=_limits(max_pending=2))
    try:
        claim = _open_claim(channel)
        _block(channel, backend, claim)
        assert _returns_promptly(lambda: [channel.deliver(_bulk(claim, rid))
                                          for rid in ("q1", "q2", "over")])
        assert _answered(channel, "over")
        refused = [b for b in channel.bodies(Opcode.ERROR) if b.get("request_id") == "over"]
        assert refused and "queue full" in refused[0]["error"]
        backend.gate.set()
        assert _answered(channel, "q2")
        served = [b["request_id"] for b in channel.bodies(Opcode.BULK)]
        assert served == ["stuck", "q1", "q2"]
    finally:
        backend.gate.set()
        host.close()


def test_frames_after_close_are_refused_not_served():
    backend = _GatedBackend()
    host, channel, session = _host(backend)
    claim = _open_claim(channel)
    host.close()
    assert _returns_promptly(lambda: channel.deliver(_bulk(claim, "late")))
    refused = [b for b in channel.bodies(Opcode.ERROR) if b.get("request_id") == "late"]
    assert refused and "closed" in refused[0]["error"]
    assert session.active_claim_count == 0


def _open_refusals(channel):
    return [b["error"] for b in channel.bodies(Opcode.ERROR) if "busy" in b.get("error", "")]


def test_new_claims_wait_while_closed_sessions_leave_too_many_threads_in_the_backend():
    from je_auto_control.utils.usb.passthrough.session_worker import abandoned_worker_threads
    assert _eventually(lambda: abandoned_worker_threads() == 0)     # none left by an earlier test
    limits = _limits(join_timeout_s=0.05, max_abandoned=1)
    backend, other = _GatedBackend(), _GatedBackend()
    gone, gone_channel, _ = _host(backend, limits=limits)
    host, channel, _ = _host(other, limits=limits)
    try:
        held = _open_claim(channel)                      # a claim held before the cap is reached
        _block(gone_channel, backend, _open_claim(gone_channel))
        gone.close()                                     # its lane thread stays inside the backend
        assert abandoned_worker_threads() == 1
        channel.deliver(Frame(op=Opcode.OPEN, payload=json.dumps(
            {"vendor_id": "1050", "product_id": "0407"}).encode("utf-8")))
        assert channel.wait_for(lambda _frames: bool(_open_refusals(channel)))
        channel.deliver(_bulk(held, "held"))
        assert _answered(channel, "held")                # what is already claimed keeps working
        backend.gate.set()
        assert _eventually(lambda: abandoned_worker_threads() == 0)
        assert _open_claim(channel) != held              # accepted again once the thread finished
    finally:
        backend.gate.set()
        gone.close()
        host.close()
