"""Peer media ownership through injected constructors, tracks and peer objects."""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from headless._webrtc_doubles import AuditLog, Bridge, FakePeerConnection, Stoppable, Track, Transceiver
from je_auto_control.utils.exception.control_signals import OperationCancelledError
from je_auto_control.utils.remote_desktop import webrtc_audio, webrtc_host, webrtc_host_media, webrtc_viewer
from je_auto_control.utils.remote_desktop.media_retirement import (
    Completion, MediaRetirementError, RetirementStatus, preserve_interrupted_owner,
)
from je_auto_control.utils.remote_desktop.webrtc_media_owners import PeerMediaOwners
from je_auto_control.utils.remote_desktop.webrtc_retirement import CleanupAttempt, PeerStopFailed, PeerStopPending


class Owner:
    def __init__(self, failed=True):
        self.failed = failed
        self.calls = 0

    @property
    def retirement_status(self):
        return RetirementStatus(True, Completion.UNCERTAIN if self.failed else Completion.CONFIRMED,
                                Completion.CONFIRMED, False, ("fake.close",) if self.failed else ())

    def start(self):
        pass

    def stop(self):
        self.calls += 1
        if self.failed:
            raise MediaRetirementError(self)


@pytest.fixture(autouse=True)
def fake_boundaries(monkeypatch):
    monkeypatch.setattr(webrtc_host, "default_audit_log", AuditLog)
    monkeypatch.setattr(webrtc_host, "get_bridge", Bridge)
    monkeypatch.setattr(webrtc_viewer, "get_bridge", Bridge)
    monkeypatch.setattr(webrtc_audio, "is_audio_backend_available", lambda: True)
    monkeypatch.setattr(webrtc_audio, "AudioPlayer", lambda **kw: Owner(False))


def make_peer(role):
    owner = (webrtc_host.WebRTCDesktopHost(token="fake") if role.startswith("host")
             else webrtc_viewer.WebRTCDesktopViewer(token="fake"))
    owner._pc = FakePeerConnection()
    owner._pc.transceivers = [Transceiver("audio")]
    return owner


def constructor_entry(owner, role):
    if role == "host-track":
        return owner._attach_host_voice
    if role == "host-receiver":
        return lambda: owner._start_opus_audio_receive(object())
    if role == "viewer-track":
        return owner._attach_opus_audio_track
    return lambda: owner._start_host_voice_play(object())


@pytest.mark.parametrize("role", ["host-track", "host-receiver", "viewer-track", "viewer-receiver"])
@pytest.mark.parametrize("control", [False, True])
def test_constructor_failure_adopts_original_owner_before_optional_catch(monkeypatch, role, control):
    owner = make_peer(role)
    resource = Owner()
    calls = []
    signal = OperationCancelledError("constructor")
    error = MediaRetirementError(resource)
    if control:
        try:
            preserve_interrupted_owner(resource, signal)
        except OperationCancelledError:
            pass
        error = RuntimeError("wrapped")
        error.__cause__ = signal

    def failed():
        calls.append(True)
        raise error

    name = "OpusMicAudioTrack" if role.endswith("track") else "OpusMicReceiver"
    monkeypatch.setattr(webrtc_audio, name, failed)
    invoke = constructor_entry(owner, role)
    if control:
        with pytest.raises(OperationCancelledError) as caught:
            invoke()
        assert caught.value is signal
    else:
        invoke()
    assert owner.media_failures[0].status is not None
    assert not owner.media_failures[0].status.retryable
    with pytest.raises(PeerStopFailed):
        invoke()
    assert len(calls) == 1
    owner._pc = None
    with pytest.raises(PeerStopFailed):
        owner.stop()
    assert resource.calls == 1
    resource.failed = False
    owner.stop()
    assert resource.calls == 2 and owner.media_failures == ()


def test_one_successful_orphan_does_not_clear_another_failure():
    owners = PeerMediaOwners()
    failed, successful = Owner(), Owner(False)
    owners.adopt("same slot", MediaRetirementError(failed))
    owners.adopt("same slot", MediaRetirementError(successful))
    attempt = CleanupAttempt()
    asyncio.run(owners.retire_orphans(attempt))
    assert len(owners.failures) == 1
    assert owners.failures[0].status == failed.retirement_status
    with pytest.raises(PeerStopFailed):
        owners.require_available("same slot")


@pytest.mark.parametrize("role", ["host", "viewer"])
def test_failed_mic_disable_retains_child_and_refuses_replacement(role):
    owner = make_peer(role)
    child = Owner()
    attr = "_mic_receiver" if role == "host" else "_mic_sender"
    setattr(owner, attr, child)
    disable = owner.disable_mic_receive if role == "host" else owner.disable_mic_send
    enable = owner.enable_mic_receive if role == "host" else owner.enable_mic_send
    with pytest.raises(MediaRetirementError):
        disable()
    with pytest.raises(PeerStopFailed):
        enable()
    assert getattr(owner, attr) is child


def test_full_peer_stop_observes_receiver_task_while_closing_other_resources():
    async def drive():
        entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Input:
            async def recv(self):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await release.wait()
                    raise

        host = make_peer("host")
        peer = host._pc
        receiver = webrtc_audio.OpusMicReceiver()
        receiver.consume(Input())
        host._opus_audio_receiver = receiver
        host._mic_receiver = mic = Stoppable()
        await entered.wait()
        stop = asyncio.create_task(host._async_stop())
        await cancelled.wait()
        assert peer.closed and mic.stopped
        assert not stop.done() and host._opus_audio_receiver is receiver
        release.set()
        await asyncio.wait_for(stop, 1)
        assert host._opus_audio_receiver is None and host._pc is None

    asyncio.run(drive())


def test_closed_loop_receiver_reports_terminal_status_without_waiting():
    async def drive():
        receiver = webrtc_audio.OpusMicReceiver()
        receiver._task = SimpleNamespace(done=lambda: False,
                                         get_loop=lambda: SimpleNamespace(is_closed=lambda: True))
        with pytest.raises(MediaRetirementError) as caught:
            await asyncio.wait_for(receiver.stop_confirmed(), .2)
        assert not caught.value.status.retryable
        assert caught.value.status.resources is Completion.UNCERTAIN

    asyncio.run(drive())


def test_media_control_signal_does_not_skip_peer_close():
    async def drive():
        host = make_peer("host")
        peer = host._pc
        signal = OperationCancelledError("stop")
        wrapped = RuntimeError("wrapped")
        wrapped.__cause__ = signal
        host._host_voice_track = Stoppable(error=wrapped)
        host._mic_receiver = mic = Stoppable()
        with pytest.raises(OperationCancelledError) as caught:
            await host._async_stop()
        assert caught.value is signal and peer.closed and mic.stopped
        assert host._host_voice_track is not None

    asyncio.run(drive())


def test_queued_viewer_detach_does_not_touch_replacement(monkeypatch):
    queued = []
    monkeypatch.setattr(webrtc_viewer, "get_bridge", lambda: SimpleNamespace(call_soon=queued.append))
    viewer = make_peer("viewer")
    old, replacement = Track("audio"), Track("audio")
    viewer._opus_audio_track = old
    viewer.toggle_opus_mic(False)
    viewer._opus_audio_track = replacement
    slot = Transceiver("audio", track=replacement)
    viewer._pc.transceivers = [slot]
    queued[0]()
    assert not replacement.stopped and slot.sender.replaced == []


@pytest.mark.parametrize("role", ["host", "viewer"])
def test_queued_renegotiation_is_inert_after_peer_replacement(role):
    owner = make_peer(role)
    pending = (owner._async_apply_renegotiate_answer("old") if role == "host"
               else owner._async_handle_renegotiate("old"))
    replacement = FakePeerConnection()
    owner._pc = replacement
    asyncio.run(pending)
    assert replacement.remote_descriptions == []


def test_host_offer_cannot_be_applied_to_replacement_after_await(monkeypatch):
    async def drive():
        entered, release = asyncio.Event(), asyncio.Event()
        host = make_peer("host")
        old = host._pc

        async def offer():
            entered.set()
            await release.wait()
            return SimpleNamespace(sdp="old")

        old.createOffer = offer
        task = asyncio.create_task(host._async_renegotiate())
        await entered.wait()
        replacement = host._pc = FakePeerConnection()
        release.set()
        await task
        assert not hasattr(replacement, "local_description_arg")

    asyncio.run(drive())


def live_host(monkeypatch):
    host = make_peer("host")
    monkeypatch.setattr(webrtc_host_media, "get_bridge", lambda: SimpleNamespace(
        call_soon=lambda fn: fn()))
    host._spawn_bg = lambda coroutine: coroutine.close()
    return host


def test_live_audio_disable_finishes_on_its_loop_and_allows_enable(monkeypatch):
    async def drive():
        host = live_host(monkeypatch)

        class Input:
            async def recv(self):
                await asyncio.Event().wait()

        receiver = webrtc_audio.OpusMicReceiver()
        receiver.consume(Input())
        host._opus_audio_receiver = receiver
        await asyncio.sleep(0)
        host.disable_accept_viewer_audio_opus()
        await asyncio.gather(*host._media_owners._tasks.values())
        await asyncio.sleep(0)
        assert host._opus_audio_receiver is None and host.media_failures == ()
        host.enable_accept_viewer_audio_opus()
        assert host._config.accept_viewer_audio_opus

    asyncio.run(drive())


def test_explicit_live_disable_retry_uses_same_original_child(monkeypatch):
    class Receiver:
        calls = 0

        def stop(self):
            pass

        async def stop_confirmed(self):
            self.calls += 1
            if self.calls == 1:
                raise OSError("temporary failure")

    async def drive():
        host = live_host(monkeypatch)
        child = host._opus_audio_receiver = Receiver()
        host.disable_accept_viewer_audio_opus()
        await asyncio.gather(*host._media_owners._tasks.values(), return_exceptions=True)
        await asyncio.sleep(0)
        assert host._opus_audio_receiver is child and host.media_failures
        with pytest.raises(PeerStopFailed):
            host.enable_accept_viewer_audio_opus()
        host.disable_accept_viewer_audio_opus()
        await asyncio.gather(*host._media_owners._tasks.values())
        await asyncio.sleep(0)
        assert child.calls == 2 and host._opus_audio_receiver is None
        assert host.media_failures == ()

    asyncio.run(drive())


def test_pending_live_video_does_not_block_independent_mic_or_peer_close(monkeypatch):
    async def drive():
        host = live_host(monkeypatch)
        entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def receive():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
                raise

        task = host._viewer_video_task = asyncio.create_task(receive())
        mic = host._mic_receiver = Stoppable()
        peer = host._pc
        await entered.wait()
        host.disable_accept_viewer_video()
        await cancelled.wait()
        with pytest.raises(PeerStopFailed):
            host.enable_accept_viewer_video()
        stop = asyncio.create_task(host._async_stop())
        for _ in range(5):
            await asyncio.sleep(0)
        assert peer.closed and mic.stopped
        assert not stop.done() and host._viewer_video_task is task
        release.set()
        await asyncio.wait_for(stop, 1)
        assert host._viewer_video_task is None

    asyncio.run(drive())


def test_live_video_error_is_visible_and_observed_once(monkeypatch):
    async def drive():
        host = live_host(monkeypatch)

        async def fail():
            raise RuntimeError("video failed")

        host._viewer_video_task = asyncio.create_task(fail())
        await asyncio.sleep(0)
        host.disable_accept_viewer_video()
        await asyncio.gather(*host._media_owners._tasks.values(), return_exceptions=True)
        await asyncio.sleep(0)
        assert host.media_failures and host._viewer_video_task is None
        with pytest.raises(PeerStopFailed):
            await host._async_stop()
        await host._async_stop()
        assert host.media_failures == ()

    asyncio.run(drive())


def test_queued_host_disable_does_not_touch_new_peer_or_receiver(monkeypatch):
    queued = []
    monkeypatch.setattr(webrtc_host_media, "get_bridge", lambda: SimpleNamespace(call_soon=queued.append))
    host = make_peer("host")
    host._opus_audio_receiver = Owner(False)
    host.disable_accept_viewer_audio_opus()
    replacement = host._opus_audio_receiver = Owner(False)
    peer = host._pc = FakePeerConnection()
    queued[0]()
    assert replacement.calls == 0 and peer.transceivers == []


def test_closed_loop_live_task_stays_owned_with_terminal_snapshot():
    owners = PeerMediaOwners()
    task = SimpleNamespace(done=lambda: False,
                           get_loop=lambda: SimpleNamespace(is_closed=lambda: True))
    owners._tasks["video"] = task
    attempt = CleanupAttempt()
    asyncio.run(owners.retire_slot("video", attempt))
    with pytest.raises(PeerStopFailed):
        attempt.finish()
    assert owners._tasks["video"] is task
    assert owners.failures[0].status.resources is Completion.UNCERTAIN
    assert not owners.failures[0].status.retryable


def test_blocked_mic_start_does_not_block_peer_close_or_loop_progress(monkeypatch):
    from je_auto_control.utils.remote_desktop import webrtc_mic
    entered, release = threading.Event(), threading.Event()
    errors = []

    class Child:
        stopped = False

        def start(self):
            entered.set()
            assert release.wait(2)

        def stop(self):
            self.stopped = True

    child = Child()
    monkeypatch.setattr(webrtc_mic, "MicUplinkReceiver", lambda: child)
    host = make_peer("host")
    peer = host._pc
    voice = host._host_voice_track = Stoppable()

    def start():
        try:
            host.enable_mic_receive()
        except BaseException as error:
            errors.append(error)

    starter = threading.Thread(target=start)
    starter.start()
    try:
        assert entered.wait(2)

        async def retire():
            with pytest.raises(PeerStopPending):
                await asyncio.wait_for(host._async_stop(), .5)
            assert peer.closed and voice.stopped and host._mic_receiver is child
            assert host.media_failures[0].status.resources is Completion.PENDING
            assert host.media_failures[0].status.retryable
            await asyncio.sleep(0)

        asyncio.run(retire())
    finally:
        release.set()
        starter.join(2)
    assert len(errors) == 1 and isinstance(errors[0], PeerStopPending)
    asyncio.run(host._async_stop())
    assert child.stopped and host._mic_receiver is None
    assert host.media_failures == ()
