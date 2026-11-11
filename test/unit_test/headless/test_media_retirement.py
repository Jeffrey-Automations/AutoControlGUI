"""Producer acknowledgements with fake resources only."""
import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.remote_desktop import audio, lan_discovery
from je_auto_control.utils.remote_desktop.media_retirement import (
    Completion, MediaRetirementError,
)


class Stream:
    def __init__(self, *, fail=(), callback=None, **kwargs):
        self.fail = set(fail)
        self.callback = callback
        self.calls = []

    def _call(self, step):
        self.calls.append(step)
        if step in self.fail:
            raise OSError(step)

    def start(self):
        self._call("start")

    def stop(self, *, ignore_errors):
        assert ignore_errors is False
        self._call("stop")

    def close(self, *, ignore_errors):
        assert ignore_errors is False
        self._call("close")

    def write(self, data):
        self._call("write")


def backend(monkeypatch, fail=()):
    streams = []

    def create(**kwargs):
        stream = Stream(fail=fail, **kwargs)
        streams.append(stream)
        return stream

    monkeypatch.setattr(audio, "_load_sounddevice", lambda: SimpleNamespace(
        PortAudioError=OSError, RawInputStream=create, RawOutputStream=create))
    return streams


@pytest.mark.parametrize("fail", [("stop",), ("close",), ("stop", "close")])
def test_audio_failure_is_retained_and_never_replayed(monkeypatch, fail):
    streams = backend(monkeypatch, fail)
    player = audio.AudioPlayer()
    player.start()
    for _ in range(2):
        with pytest.raises(MediaRetirementError) as caught:
            player.stop()
        assert caught.value.owner is player
        assert isinstance(caught.value, AutoControlException)
    assert streams[0].calls == ["start", "stop", "close"]
    assert not player.is_running
    assert not player.retirement_status.retryable
    with pytest.raises(MediaRetirementError):
        player.start()
    assert len(streams) == 1


def test_audio_failed_start_retains_failed_close(monkeypatch):
    streams = backend(monkeypatch, ("start", "close"))
    player = audio.AudioPlayer()
    with pytest.raises(MediaRetirementError) as caught:
        player.start()
    assert caught.value.owner is player
    assert player._lease.stream is streams[0]
    assert streams[0].calls == ["start", "close"]


def test_audio_cleanup_does_not_reload_backend(monkeypatch):
    streams = backend(monkeypatch)
    player = audio.AudioPlayer()
    player.start()
    monkeypatch.setattr(audio, "_load_sounddevice", lambda: pytest.fail("reload"))
    player.stop()
    player.stop()
    assert streams[0].calls == ["start", "stop", "close"]
    assert player.retirement_status.complete


def test_capture_inflight_operation_defers_cleanup_and_rejects_old_generation(monkeypatch):
    streams = backend(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    blocks = []

    def block(data):
        blocks.append(data)
        entered.set()
        assert release.wait(2)

    capture = audio.AudioCapture(block)
    capture.start()
    old = streams[0]
    thread = threading.Thread(target=old.callback, args=(b"one", 1, None, None))
    thread.start()
    try:
        assert entered.wait(2)
        with pytest.raises(MediaRetirementError):
            capture.stop()
        assert capture.retirement_status.retryable
        assert old.calls == ["start"]
        old.callback(b"late", 1, None, None)
    finally:
        release.set()
        thread.join(2)
    capture.stop()
    capture.start()
    old.callback(b"replaced", 1, None, None)
    assert blocks == [b"one"]
    capture.stop()


def test_callback_can_request_its_own_retirement_without_deadlock(monkeypatch):
    streams = backend(monkeypatch)
    results = []

    def stop(_data):
        with pytest.raises(MediaRetirementError):
            capture.stop()
        results.append(True)

    capture = audio.AudioCapture(stop)
    capture.start()
    streams[0].callback(b"one", 1, None, None)
    assert results == [True]
    capture.stop()


class Encoder:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def encode(self, frame):
        self.calls.append(frame)
        yield "packet"
        if self.fail:
            raise OSError("partial flush")


class Container:
    def __init__(self, *, fail_close=False, fail_mux=False):
        self.close_calls = 0
        self.packets = []
        self.fail_close = fail_close
        self.fail_mux = fail_mux

    def mux(self, packet):
        self.packets.append(packet)
        if self.fail_mux:
            raise OSError("partial mux")

    def close(self):
        self.close_calls += 1
        if self.fail_close:
            raise OSError("trailer")


@pytest.mark.parametrize("flush,mux,close", [(True, False, False), (False, True, False),
                                           (False, False, True), (True, False, True)])
def test_recorder_uncertain_flush_or_close_never_becomes_saved(flush, mux, close):
    from je_auto_control.utils.remote_desktop.session_recorder import SessionRecorder
    recorder = SessionRecorder("unused.mp4")
    stream, container = Encoder(flush), Container(fail_close=close, fail_mux=mux)
    recorder._stream, recorder._container = stream, container
    for _ in range(2):
        with pytest.raises(MediaRetirementError):
            recorder.stop()
    assert stream.calls == [None]
    assert container.packets == ["packet"]
    assert container.close_calls == 1
    assert recorder.retirement_status.finalization is Completion.UNCERTAIN
    assert not recorder.retirement_status.retryable
    if close:
        assert recorder._container is container


def test_recorder_setup_failure_retains_container_when_close_fails(monkeypatch):
    from je_auto_control.utils.remote_desktop import session_recorder
    container = Container(fail_close=True)
    container.add_stream = lambda *args, **kwargs: object()
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_recorder.av, "open", lambda *args, **kwargs: container)
    recorder = session_recorder.SessionRecorder("unused.mp4")
    recorder.write_frame(SimpleNamespace(width=1, height=1))
    assert recorder._container is container
    assert not recorder.is_active
    with pytest.raises(MediaRetirementError):
        recorder.stop()
    assert container.close_calls == 1


def advertiser(monkeypatch, *, fail_unregister=False, close_failures=0):
    calls = []

    def unregister(_info):
        calls.append("unregister")
        if fail_unregister:
            raise OSError("goodbye")

    def close():
        calls.append("close")
        if calls.count("close") <= close_failures:
            raise OSError("close")

    zc = SimpleNamespace(register_service=lambda info: None,
                         unregister_service=unregister, close=close)
    monkeypatch.setattr(lan_discovery, "_AVAILABLE", True)
    monkeypatch.setattr(lan_discovery, "Zeroconf", lambda: zc)
    monkeypatch.setattr(lan_discovery, "ServiceInfo", lambda *a, **k: object())
    monkeypatch.setattr(lan_discovery, "_local_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(lan_discovery.socket, "gethostname", lambda: "fake")
    return lan_discovery.HostAdvertiser(host_id="fake"), calls, zc


def test_advertiser_retry_closes_original_without_repeating_unregister(monkeypatch):
    owner, calls, zc = advertiser(monkeypatch, close_failures=1)
    with pytest.raises(MediaRetirementError) as caught:
        owner.stop()
    assert caught.value.owner is owner and owner._zc is zc
    assert owner.retirement_status.retryable
    owner.stop()
    owner.stop()
    assert calls == ["unregister", "close", "close"]


def test_advertiser_closed_does_not_prove_goodbye(monkeypatch):
    owner, calls, _ = advertiser(monkeypatch, fail_unregister=True)
    for _ in range(2):
        with pytest.raises(MediaRetirementError):
            owner.stop()
    assert owner.retirement_status.resources is Completion.CONFIRMED
    assert owner.retirement_status.finalization is Completion.UNCERTAIN
    assert not owner.retirement_status.retryable
    assert calls == ["unregister", "close"]


def test_advertiser_constructor_error_hands_out_cleanup_owner(monkeypatch):
    owner, _, zc = advertiser(monkeypatch, close_failures=1)
    zc.register_service = lambda info: (_ for _ in ()).throw(OSError("register"))
    with pytest.raises(MediaRetirementError) as caught:
        lan_discovery.HostAdvertiser(host_id="another")
    assert caught.value.owner is not owner
    caught.value.owner.stop()


def test_opus_receiver_retains_pending_task_until_observed(monkeypatch):
    from je_auto_control.utils.remote_desktop import webrtc_audio
    monkeypatch.setattr(webrtc_audio, "is_audio_backend_available", lambda: True)
    monkeypatch.setattr(webrtc_audio, "AudioPlayer", lambda **kw: SimpleNamespace(
        start=lambda: None, stop=lambda: None))

    async def run():
        receiver = webrtc_audio.OpusMicReceiver()
        task = asyncio.create_task(asyncio.sleep(100))
        receiver._task = task
        with pytest.raises(MediaRetirementError):
            receiver.stop()
        assert receiver._task is task
        with pytest.raises(RuntimeError):
            receiver.consume(object())
        await asyncio.gather(task, return_exceptions=True)
        receiver.stop()
        assert receiver.retirement_status.complete

    asyncio.run(run())


def test_recorder_success_is_idempotent_and_rejects_late_frames():
    from je_auto_control.utils.remote_desktop.session_recorder import SessionRecorder
    recorder = SessionRecorder("unused.mp4")
    stream, container = Encoder(), Container()
    recorder._stream, recorder._container = stream, container
    recorder.stop()
    recorder.write_frame(object())
    recorder.stop()
    assert recorder.retirement_status.complete
    assert stream.calls == [None] and container.close_calls == 1


def test_host_audio_failure_does_not_skip_socket_or_client_cleanup():
    from je_auto_control.utils.remote_desktop.host import RemoteDesktopHost
    calls = []

    def failed_stop():
        calls.append("audio")
        raise OSError("retained failure")

    host = object.__new__(RemoteDesktopHost)
    capture = SimpleNamespace(stop=failed_stop)
    host._audio_capture = capture
    host._lifecycle_lock = threading.Lock()
    host._shutdown = threading.Event()
    host._listen_sock = SimpleNamespace(close=lambda: calls.append("socket"))
    host._frame_cond = threading.Condition()
    host._clients_lock = threading.Lock()
    host._clients = [SimpleNamespace(stop=lambda: calls.append("client"))]
    host._file_receiver = None
    host._accept_thread = host._capture_thread = host._cursor_thread = None
    with pytest.raises(OSError):
        host.stop()
    assert calls == ["audio", "socket", "client"]
    assert host._audio_capture is capture
    with pytest.raises(OSError):
        host.stop()
    assert calls[-1] == "audio"


def test_opus_capture_failure_retains_child_and_wakes_recv(monkeypatch):
    from aiortc.mediastreams import MediaStreamError
    from je_auto_control.utils.remote_desktop import webrtc_audio
    streams = backend(monkeypatch, ("close",))
    monkeypatch.setattr(webrtc_audio, "is_audio_backend_available", lambda: True)

    async def run():
        track = webrtc_audio.OpusMicAudioTrack()
        receive = asyncio.create_task(track.recv())
        await asyncio.sleep(0)
        child = track._capture
        with pytest.raises(MediaRetirementError):
            track.stop()
        assert track._capture is child and track.readyState == "ended"
        with pytest.raises(MediaStreamError):
            await asyncio.wait_for(receive, 1)
        track._enqueue(b"late")
        assert track._queue.empty()

    asyncio.run(run())
    assert streams[0].calls == ["start", "stop", "close"]


def test_mic_queued_send_does_not_cross_replacement_generation(monkeypatch):
    from je_auto_control.utils.remote_desktop import webrtc_mic
    backend(monkeypatch)
    queued, sent = [], []
    monkeypatch.setattr(webrtc_mic, "is_audio_backend_available", lambda: True)
    monkeypatch.setattr(webrtc_mic, "get_bridge", lambda: SimpleNamespace(
        call_soon=lambda fn, *args: queued.append((fn, args))))
    sender = webrtc_mic.MicUplinkSender(SimpleNamespace(send=sent.append))
    sender.start()
    sender._on_block(b"old")
    sender.stop()
    sender.start()
    for fn, args in queued:
        fn(*args)
    assert sent == []
    sender.stop()


def interruption(wrapped):
    from je_auto_control.utils.exception.control_signals import OperationCancelledError
    signal = OperationCancelledError("fake")
    error = RuntimeError("wrapped") if wrapped else signal
    if wrapped:
        error.__cause__ = signal
    return signal, error


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("producer", ["audio", "recorder", "advertiser"])
def test_interruption_identity_survives_independent_close(monkeypatch, producer, wrapped):
    signal, error = interruption(wrapped)

    def interrupted(*args, **kwargs):
        raise error

    if producer == "audio":
        streams = backend(monkeypatch)
        owner = audio.AudioPlayer()
        owner.start()
        streams[0].stop = interrupted
        def closed():
            return "close" in streams[0].calls
    elif producer == "recorder":
        from je_auto_control.utils.remote_desktop.session_recorder import SessionRecorder
        owner = SessionRecorder("unused.mp4")
        container = Container()
        owner._container = container
        owner._stream = SimpleNamespace(encode=interrupted)
        def closed():
            return container.close_calls == 1
    else:
        owner, calls, zc = advertiser(monkeypatch)
        zc.unregister_service = interrupted
        def closed():
            return "close" in calls
    with pytest.raises(type(signal)) as caught:
        owner.stop()
    assert caught.value is signal
    assert closed()


def test_play_during_factory_acquisition_is_rejected(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    streams = backend(monkeypatch)
    original = audio._load_sounddevice()

    def factory(**kwargs):
        entered.set()
        assert release.wait(2)
        return original.RawOutputStream(**kwargs)

    monkeypatch.setattr(audio, "_load_sounddevice", lambda: SimpleNamespace(
        PortAudioError=OSError, RawOutputStream=factory))
    player = audio.AudioPlayer()
    thread = threading.Thread(target=player.start)
    thread.start()
    try:
        assert entered.wait(2)
        assert not player.is_running
        with pytest.raises(RuntimeError):
            player.play(b"pcm")
    finally:
        release.set()
        thread.join(2)
    player.stop()
    assert streams[0].calls == ["start", "stop", "close"]


def test_opus_loop_close_race_does_not_skip_capture_cleanup(monkeypatch):
    from je_auto_control.utils.remote_desktop import webrtc_audio
    streams = backend(monkeypatch)
    monkeypatch.setattr(webrtc_audio, "is_audio_backend_available", lambda: True)

    def broken_schedule(*args):
        raise RuntimeError("loop closed")

    async def run():
        track = webrtc_audio.OpusMicAudioTrack()
        track._loop = SimpleNamespace(is_closed=lambda: False,
                                      call_soon_threadsafe=broken_schedule)
        with pytest.raises(RuntimeError, match="loop closed"):
            track.stop()
        assert track._capture is None

    asyncio.run(run())
    assert streams[0].calls == ["start", "stop", "close"]


def test_opus_done_task_failure_is_observed_once_after_player_cleanup(monkeypatch):
    from je_auto_control.utils.remote_desktop import webrtc_audio
    streams = backend(monkeypatch)
    monkeypatch.setattr(webrtc_audio, "is_audio_backend_available", lambda: True)
    signal, error = interruption(True)

    async def fail():
        raise error

    async def run():
        receiver = webrtc_audio.OpusMicReceiver()
        receiver._task = asyncio.create_task(fail())
        await asyncio.sleep(0)
        with pytest.raises(type(signal)) as caught:
            receiver.stop()
        assert caught.value is signal
        assert receiver._task is None
        assert receiver._player_retired
        receiver.stop()
        assert receiver.retirement_status.complete

    asyncio.run(run())
    assert streams[0].calls == ["start", "stop", "close"]


def test_mic_retained_failure_refuses_new_start(monkeypatch):
    from je_auto_control.utils.remote_desktop import webrtc_mic
    streams = backend(monkeypatch, ("close",))
    monkeypatch.setattr(webrtc_mic, "is_audio_backend_available", lambda: True)
    sender = webrtc_mic.MicUplinkSender(object())
    sender.start()
    child = sender._capture
    with pytest.raises(MediaRetirementError):
        sender.stop()
    with pytest.raises(MediaRetirementError):
        sender.start()
    assert sender._capture is child and len(streams) == 1


def test_audio_hard_interrupt_still_attempts_close(monkeypatch):
    streams = backend(monkeypatch)
    owner = audio.AudioPlayer()
    owner.start()
    signal = KeyboardInterrupt()

    def interrupted(**kwargs):
        raise signal

    streams[0].stop = interrupted
    with pytest.raises(KeyboardInterrupt) as caught:
        owner.stop()
    assert caught.value is signal
    assert streams[0].calls == ["start", "close"]


def test_constructor_interruption_has_explicit_original_cleanup_owner(monkeypatch):
    from je_auto_control.utils.remote_desktop.media_retirement import interrupted_retirement_owners
    _, _, zc = advertiser(monkeypatch, close_failures=1)
    signal, error = interruption(True)

    def interrupted(_info):
        raise error

    zc.register_service = interrupted
    with pytest.raises(type(signal)) as caught:
        lan_discovery.HostAdvertiser(host_id="interrupted")
    assert caught.value is signal
    (owner,) = interrupted_retirement_owners(signal)
    assert owner._zc is zc and owner.retirement_status.retryable
    owner.stop()
    assert owner.retirement_status.complete


@pytest.mark.parametrize("kind", ["sender", "receiver"])
def test_mic_stop_waiting_for_start_keeps_admission_closed(monkeypatch, kind):
    from je_auto_control.utils.remote_desktop import webrtc_mic
    entered, release, stopping = threading.Event(), threading.Event(), threading.Event()
    children, sent = [], []

    class Child:
        def __init__(self, **kwargs):
            self.callback = kwargs.get("on_block")
            children.append(self)

        def start(self):
            entered.set()
            assert release.wait(2)

        def stop(self):
            pass

    class Lock:
        def __init__(self):
            self.lock = threading.Lock()

        def __enter__(self):
            if threading.current_thread().name == "retire":
                stopping.set()
            self.lock.acquire()

        def __exit__(self, *args):
            self.lock.release()

    monkeypatch.setattr(webrtc_mic, "is_audio_backend_available", lambda: True)
    monkeypatch.setattr(webrtc_mic, "AudioCapture", Child)
    monkeypatch.setattr(webrtc_mic, "AudioPlayer", Child)
    monkeypatch.setattr(webrtc_mic, "get_bridge", lambda: SimpleNamespace(
        call_soon=lambda fn, *args: fn(*args)))
    owner = (webrtc_mic.MicUplinkSender(SimpleNamespace(send=sent.append)) if kind == "sender"
             else webrtc_mic.MicUplinkReceiver())
    owner._lock = Lock()
    starter = threading.Thread(target=owner.start)
    stopper = threading.Thread(target=owner.stop, name="retire")
    starter.start()
    try:
        assert entered.wait(2)
        stopper.start()
        assert stopping.wait(2)
    finally:
        release.set()
        starter.join(2)
        if stopper.ident is not None:
            stopper.join(2)
    assert owner._stopped
    if kind == "sender":
        children[0].callback(b"late PCM")
        assert sent == []
