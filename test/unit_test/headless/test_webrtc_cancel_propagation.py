"""Cancelling a child task during cleanup must not swallow the cleaner's own cancellation.

``except asyncio.CancelledError: pass`` around ``await child`` also caught the
cancellation of the task doing the waiting (SonarCloud python:S7497 on #552):
cancelled mid-cleanup, that task carried on as if nothing had happened.
"""
import asyncio

import pytest

pytest.importorskip("aiortc", exc_type=ImportError)

from je_auto_control.utils.remote_desktop import webrtc_peer_cleanup  # noqa: E402  # reason: optional media dependencies


async def _slow_to_stop(release: asyncio.Event) -> None:
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        await release.wait()     # cleanup that takes a while
        raise


def test_a_cancelled_child_is_waited_for_and_its_cancellation_absorbed():
    async def drive():
        release = asyncio.Event()
        release.set()
        child = asyncio.create_task(_slow_to_stop(release))
        await asyncio.sleep(0)
        await webrtc_peer_cleanup._cancel_task(child)
        return child.cancelled()
    assert asyncio.run(drive()) is True


def test_the_cleaners_own_cancellation_propagates():
    async def drive():
        release = asyncio.Event()
        child = asyncio.create_task(_slow_to_stop(release))
        await asyncio.sleep(0)
        cleaner = asyncio.create_task(webrtc_peer_cleanup._cancel_task(child))
        await asyncio.sleep(0.01)    # the cleaner now waits on the child
        cleaner.cancel()
        release.set()
        try:
            await cleaner
        except asyncio.CancelledError:
            return "cancelled"
        return "finished"
    assert asyncio.run(drive()) == "cancelled"
