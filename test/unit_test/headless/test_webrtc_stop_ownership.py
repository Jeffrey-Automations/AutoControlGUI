"""Real peer owners retain fake pending resources across explicit stop retries."""
import asyncio
from concurrent.futures import Future

import pytest

from headless._webrtc_doubles import Bridge, FakePeerConnection, Stoppable
from je_auto_control.utils.remote_desktop import webrtc_host, webrtc_viewer, webrtc_retirement
from je_auto_control.utils.remote_desktop.webrtc_retirement import PeerStopFailed, PeerStopPending
from je_auto_control.utils.remote_desktop.file_sync import FolderSyncEngine


@pytest.fixture(params=[webrtc_host.WebRTCDesktopHost, webrtc_viewer.WebRTCDesktopViewer])
def owner(request, monkeypatch):
    monkeypatch.setattr(webrtc_retirement, "_STOP_TIMEOUT_S", 0)
    return request.param(token="test-token")


class DeferredBridge:
    def __init__(self):
        self.calls = []
        self.future = Future()

    def submit(self, coroutine):
        self.calls.append(coroutine)
        return self.future

    def complete(self):
        try:
            result = asyncio.run(self.calls[0])
        except BaseException as error:
            self.future.set_exception(error)
        else:
            self.future.set_result(result)


def bind_bridge(monkeypatch, bridge):
    for module in (webrtc_host, webrtc_viewer):
        monkeypatch.setattr(module, "get_bridge", lambda: bridge)


def test_pending_stop_reuses_one_future_and_blocks_public_and_async_restart(owner, monkeypatch):
    bridge = DeferredBridge()
    bind_bridge(monkeypatch, bridge)
    peer = FakePeerConnection()
    owner._pc = peer
    owner._authenticated = True
    try:
        for _ in range(2):
            with pytest.raises(PeerStopPending):
                owner.stop()
        assert len(bridge.calls) == 1
        assert owner._pc is peer
        assert not owner.authenticated
        assert owner._closed.is_set()
        if isinstance(owner, webrtc_host.WebRTCDesktopHost):
            with pytest.raises(PeerStopPending):
                owner.create_offer()
            restart = owner._async_create_offer()
        else:
            with pytest.raises(PeerStopPending):
                owner.process_offer("v=0")
            restart = owner._async_process_offer("v=0")
        with pytest.raises(PeerStopPending):
            asyncio.run(restart)
    finally:
        bridge.complete()
    owner.stop()
    assert peer.closed
    assert owner._pc is None
    assert len(bridge.calls) == 1


def test_failed_media_stays_owned_while_peer_closes_then_explicit_retry_succeeds(owner, monkeypatch):
    bind_bridge(monkeypatch, Bridge())
    peer = FakePeerConnection()
    owner._pc = peer
    failed = Stoppable(error=OSError("sensitive device details"))
    attr = "_host_voice_track" if isinstance(owner, webrtc_host.WebRTCDesktopHost) else "_host_voice_receiver"
    setattr(owner, attr, failed)
    with pytest.raises(PeerStopFailed) as caught:
        owner.stop()
    assert "sensitive" not in str(caught.value)
    assert peer.closed
    assert getattr(owner, attr) is failed
    with pytest.raises(PeerStopFailed):
        owner._retirement.require_startable()
    failed._error = None
    owner.stop()
    assert failed.stopped
    assert getattr(owner, attr) is None
    owner._retirement.require_startable()


def test_queued_stop_targets_original_peer_identity(owner):
    original, replacement = FakePeerConnection(), FakePeerConnection()
    owner._pc = original
    queued = owner._async_stop()
    owner._pc = replacement
    asyncio.run(queued)
    assert owner._pc is replacement
    assert not replacement.closed


def test_delayed_auth_failure_cannot_close_replacement(monkeypatch):
    async def drive():
        host = webrtc_host.WebRTCDesktopHost(token="test-token")
        host._pc = FakePeerConnection()
        callbacks = []
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "call_later", lambda delay, callback: callbacks.append(callback))
        host._schedule_close_after_fail()
        replacement = FakePeerConnection()
        host._pc = replacement
        callbacks[0]()
        await asyncio.gather(*host._background_tasks)
        assert host._pc is replacement
        assert not replacement.closed
    asyncio.run(drive())


def test_stop_waits_for_cancel_resistant_frame_task():
    async def drive():
        viewer = webrtc_viewer.WebRTCDesktopViewer(token="test-token")
        peer = FakePeerConnection()
        viewer._pc = peer
        entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def frames():
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
        task = asyncio.create_task(frames())
        viewer._receive_task = task
        await entered.wait()
        stop = asyncio.create_task(viewer._async_stop())
        await cancelled.wait()
        assert not stop.done()
        assert peer.closed
        assert viewer._receive_task is task
        with pytest.raises(PeerStopFailed):
            await viewer._async_process_offer("v=0")
        release.set()
        await stop
        assert viewer._receive_task is None
    asyncio.run(drive())


def test_folder_sync_confirmation_observes_original_worker(tmp_path):
    engine = FolderSyncEngine(watch_dir=tmp_path, sender=lambda *_: None)
    class Worker:
        alive = True
        def join(self, timeout):
            assert timeout == 2.0
        def is_alive(self):
            return self.alive
    worker = Worker()
    engine._thread = worker
    assert not engine.stop_confirmed()
    assert engine.stop_requested
    assert engine._thread is worker
    worker.alive = False
    assert engine.stop_confirmed()


def test_stop_preserves_explicit_interruption_identity(owner, monkeypatch):
    from je_auto_control.utils.exception.control_signals import OperationCancelledError
    bind_bridge(monkeypatch, Bridge())
    signal = OperationCancelledError("test-stop")
    wrapped = RuntimeError("wrapped cancellation")
    wrapped.__cause__ = signal
    resource = Stoppable(error=wrapped)
    attr = "_host_voice_track" if isinstance(owner, webrtc_host.WebRTCDesktopHost) else "_host_voice_receiver"
    setattr(owner, attr, resource)
    owner._pc = FakePeerConnection()
    with pytest.raises(OperationCancelledError) as caught:
        owner.stop()
    assert caught.value is signal
    assert getattr(owner, attr) is resource


def test_failed_frame_task_is_reported_once_and_completed_ownership_is_released():
    async def drive():
        viewer = webrtc_viewer.WebRTCDesktopViewer(token="test-token")
        async def failed():
            raise RuntimeError("frame processing failed")
        task = asyncio.create_task(failed())
        await asyncio.wait({task})
        viewer._receive_task = task
        with pytest.raises(PeerStopFailed, match="receive task"):
            await viewer._async_stop()
        assert task.done()
        assert viewer._receive_task is None
        await viewer._async_stop()
        viewer._retirement.require_startable()
    asyncio.run(drive())


def test_bridge_submission_failure_remains_retryable(owner, monkeypatch):
    class UnavailableBridge:
        def submit(self, _coroutine):
            raise OSError("bridge unavailable")
    bind_bridge(monkeypatch, UnavailableBridge())
    peer = FakePeerConnection()
    owner._pc = peer
    with pytest.raises(PeerStopFailed):
        owner.stop()
    assert owner._pc is peer
    bind_bridge(monkeypatch, Bridge())
    owner.stop()
    assert peer.closed
