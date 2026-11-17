"""File-request cancellation observes the original fake sender's actual completion."""
import asyncio
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextvars import ContextVar
import threading

import pytest

from je_auto_control.utils.remote_desktop import webrtc_file_tasks as requests


async def wait_for(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.parametrize('failure', [False, True])
def test_repeated_cancel_keeps_sender_and_queue_owned_until_actual_exit(failure):
    entered, release, exited, cancellation_seen = (threading.Event() for _ in range(4))
    calls, failures = [], []

    def sender(path, remote_name=None, *, cancelled=None):
        calls.append(path)
        entered.set()
        try:
            if not release.wait(3):
                raise TimeoutError('test sender was not released')
            if cancelled():
                cancellation_seen.set()
            if failure:
                raise OSError('late provider failure')
        finally:
            exited.set()

    async def drive():
        owned, channel = set(), object()
        requests.start_file_request(owned, sender, 'first', 'name', channel, lambda: True, failures.append)
        requests.start_file_request(owned, sender, 'queued', 'name', channel, lambda: True, failures.append)
        stopping = None
        try:
            await wait_for(entered.is_set)
            stopping = asyncio.create_task(requests.cancel_file_requests(owned))
            await wait_for(lambda: len(owned) == 1)
            original = next(iter(owned))
            original.cancel('second stop')
            await asyncio.sleep(0)
            assert not original.done()
            assert not stopping.done()
            assert not exited.is_set()
            assert any(queue.channel is channel and queue.users == 1 for queue in requests._queues.values())
            assert calls == ['first']
            release.set()
            await asyncio.wait_for(stopping, 3)
            assert exited.is_set() and cancellation_seen.is_set()
            assert not owned
            assert not any(queue.channel is channel for queue in requests._queues.values())
            assert failures == []
        finally:
            release.set()
            if stopping is not None:
                await asyncio.gather(stopping, return_exceptions=True)
            await requests.cancel_file_requests(owned)

    asyncio.run(drive())


@pytest.mark.parametrize('outcome', ['success', 'error', 'cancel'])
def test_sender_context_and_uncancelled_results_preserve_existing_contract(outcome):
    context = ContextVar('sender-authority', default='ambient')
    observed, failures = [], []

    def sender(path, remote_name=None, *, cancelled=None):
        observed.append((context.get(), path, remote_name, cancelled()))
        if outcome == 'error':
            raise OSError('provider failed')
        if outcome == 'cancel':
            raise CancelledError()

    async def drive():
        token = context.set('original')
        try:
            await requests.push_requested_file(sender, 'file', 'name', lambda: True, failures.append)
        finally:
            context.reset(token)

    asyncio.run(drive())
    assert observed == [('original', 'file', 'name', False)]
    assert failures == (['provider failed'] if outcome == 'error' else [])


def test_cancellation_before_request_starts_never_submits_sender():
    calls = []

    async def drive():
        owned = set()
        requests.start_file_request(owned, lambda *args, **kwargs: calls.append(args),
                                    'file', 'name', object(), lambda: True, calls.append)
        await requests.cancel_file_requests(owned)
        assert not owned

    asyncio.run(drive())
    assert calls == []


def test_cancelled_work_waiting_for_executor_capacity_does_not_enter_sender():
    entered, release = threading.Event(), threading.Event()
    calls = []

    def occupy_executor():
        entered.set()
        if not release.wait(3):
            raise TimeoutError('executor blocker was not released')

    async def drive():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        blocker = loop.run_in_executor(None, occupy_executor)
        task = None
        try:
            await wait_for(entered.is_set)
            task = asyncio.create_task(requests.push_requested_file(
                lambda *args, **kwargs: calls.append(args), 'file', 'name', lambda: True, calls.append))
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert calls == []
        finally:
            release.set()
            await blocker
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(drive())
