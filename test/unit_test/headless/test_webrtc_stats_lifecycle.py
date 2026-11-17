"""Statistics lifecycle uses a queued fake bridge, never native media or a peer."""
import asyncio
import gc
import weakref
from concurrent.futures import Future
import sys
import threading
from types import SimpleNamespace

import pytest

from je_auto_control.utils.remote_desktop import webrtc_stats


class PendingFuture(Future):
    def result(self, timeout=None):
        raise AssertionError("start must not wait for the bridge")


class QueuedBridge:
    def __init__(self):
        self.calls = []
        self.future = PendingFuture()

    def submit(self, coroutine):
        self.calls.append(coroutine)
        return self.future

    def close(self):
        for coroutine in self.calls:
            coroutine.close()


@pytest.fixture
def bridge(monkeypatch):
    queued = QueuedBridge()
    monkeypatch.setitem(sys.modules, "je_auto_control.utils.remote_desktop.webrtc_transport",
                        SimpleNamespace(get_bridge=lambda: queued))
    yield queued
    queued.close()


def test_start_returns_before_bridge_runs_and_duplicate_start_submits_once(bridge):
    poller = webrtc_stats.StatsPoller(None, lambda snapshot: None)
    poller.start()
    poller.start()
    assert len(bridge.calls) == 1
    assert not bridge.future.done()
    poller.stop()
    assert bridge.future.cancelled()


def test_stop_before_start_never_looks_up_bridge(monkeypatch):
    def unavailable():
        raise AssertionError("a stopped poller must not acquire a bridge")
    monkeypatch.setitem(sys.modules, "je_auto_control.utils.remote_desktop.webrtc_transport",
                        SimpleNamespace(get_bridge=unavailable))
    poller = webrtc_stats.StatsPoller(None, lambda snapshot: None)
    poller.stop()
    poller.start()
    poller.stop()


def test_stop_before_queued_coroutine_runs_prevents_sampling(bridge):
    class Peer:
        async def getStats(self):
            raise AssertionError("stopped queued work must not sample")
    poller = webrtc_stats.StatsPoller(Peer(), lambda snapshot: pytest.fail("late sample"))
    poller.start()
    poller.stop()
    asyncio.run(bridge.calls[0])
    assert bridge.future.cancelled()


def test_stop_during_submission_does_not_wait_and_cancels_arriving_future(bridge):
    entered, finish = threading.Event(), threading.Event()
    original = bridge.submit
    def submit(coroutine):
        entered.set()
        assert finish.wait(2)
        return original(coroutine)
    bridge.submit = submit
    poller = webrtc_stats.StatsPoller(None, lambda snapshot: None)
    errors = []
    def start():
        try:
            poller.start()
        except BaseException as error:
            errors.append(error)
    worker = threading.Thread(target=start)
    worker.start()
    try:
        assert entered.wait(2)
        poller.stop()
        assert worker.is_alive()
    finally:
        finish.set()
        worker.join(2)
    assert not worker.is_alive() and not errors
    assert bridge.future.cancelled()
    poller.start()
    assert len(bridge.calls) == 1


def test_sample_finishing_after_stop_is_not_delivered(monkeypatch):
    async def run():
        sampled, finish = asyncio.Event(), asyncio.Event()
        class Peer:
            async def getStats(self):
                sampled.set()
                await finish.wait()
                return {}
        delivered = []
        poller = webrtc_stats.StatsPoller(Peer(), delivered.append)
        async def tick(delay):
            return None
        monkeypatch.setattr(webrtc_stats.asyncio, "sleep", tick)
        task = asyncio.create_task(poller._loop())
        await sampled.wait()
        poller.stop()
        finish.set()
        await task
        assert delivered == []
    asyncio.run(run())


def test_submission_failure_closes_coroutine_and_reports_error(bridge, monkeypatch):
    captured, warnings = [], []
    def submit(coroutine):
        captured.append(coroutine)
        raise RuntimeError("bridge closed")
    bridge.submit = submit
    monkeypatch.setattr(webrtc_stats.autocontrol_logger, "warning", lambda *args: warnings.append(args))
    poller = webrtc_stats.StatsPoller(None, lambda snapshot: None)
    poller.start()
    assert captured[0].cr_frame is None
    assert warnings and "bridge closed" in str(warnings)
    poller.stop()


def test_synchronous_future_completion_is_safe(bridge, monkeypatch):
    bridge.future.set_result(None)
    warnings = []
    monkeypatch.setattr(webrtc_stats.autocontrol_logger, "warning", lambda *args: warnings.append(args))
    poller = webrtc_stats.StatsPoller(None, lambda snapshot: None)
    poller.start()
    poller.stop()
    assert warnings == []


def test_async_failure_is_observed_without_waiting(bridge, monkeypatch):
    warnings = []
    monkeypatch.setattr(webrtc_stats.autocontrol_logger, "warning", lambda *args: warnings.append(args))
    poller = webrtc_stats.StatsPoller(None, lambda snapshot: None)
    poller.start()
    bridge.future.set_exception(RuntimeError("peer closed"))
    assert warnings and "peer closed" in str(warnings)
    poller.stop()


def test_started_poller_delivers_samples_until_callback_stops_it(bridge, monkeypatch):
    delivered = []
    class Peer:
        async def getStats(self):
            return {}
    poller = webrtc_stats.StatsPoller(Peer(), lambda snapshot: (delivered.append(snapshot), poller.stop()))
    async def tick(delay):
        return None
    monkeypatch.setattr(webrtc_stats.asyncio, "sleep", tick)
    poller.start()
    asyncio.run(bridge.calls[0])
    assert len(delivered) == 1
    assert bridge.future.cancelled()


def test_stop_during_initial_interval_does_not_query_peer(bridge, monkeypatch):
    class Peer:
        async def getStats(self):
            raise AssertionError("stop during interval must skip query")
    poller = webrtc_stats.StatsPoller(Peer(), lambda snapshot: pytest.fail("late sample"))
    async def tick(delay):
        poller.stop()
    monkeypatch.setattr(webrtc_stats.asyncio, "sleep", tick)
    poller.start()
    asyncio.run(bridge.calls[0])
    assert bridge.future.cancelled()


def test_stop_drops_callback_owner_even_when_bridge_has_not_run(bridge):
    class Receiver:
        def receive(self, snapshot):
            raise AssertionError("stopped callback")
    receiver = Receiver()
    reference = weakref.ref(receiver)
    poller = webrtc_stats.StatsPoller(None, receiver.receive)
    poller.start()
    del receiver
    assert reference() is not None
    poller.stop()
    gc.collect()
    assert reference() is None


def test_previous_callback_owner_is_not_retained_during_next_sample(monkeypatch):
    async def run():
        second_sample, finish = asyncio.Event(), asyncio.Event()
        class Peer:
            count = 0
            async def getStats(self):
                self.count += 1
                if self.count == 2:
                    second_sample.set()
                    await finish.wait()
                return {}
        class Receiver:
            def receive(self, snapshot):
                pass
        receiver = Receiver()
        reference = weakref.ref(receiver)
        poller = webrtc_stats.StatsPoller(Peer(), receiver.receive)
        async def tick(delay):
            return None
        monkeypatch.setattr(webrtc_stats.asyncio, "sleep", tick)
        task = asyncio.create_task(poller._loop())
        await second_sample.wait()
        del receiver
        poller.stop()
        gc.collect()
        assert reference() is None
        finish.set()
        await task
    asyncio.run(run())
