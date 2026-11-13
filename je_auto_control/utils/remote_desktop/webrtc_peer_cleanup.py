"""Software cleanup of a serialized peer generation, retaining failed resources."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from je_auto_control.utils.remote_desktop.webrtc_file_receive import close_file_receiver
from je_auto_control.utils.remote_desktop.webrtc_file_tasks import cancel_file_requests
from je_auto_control.utils.remote_desktop.webrtc_retirement import CleanupAttempt, Resource
from je_auto_control.utils.remote_desktop.webrtc_media_owners import AsyncMediaStop, PeerMediaOwners

if TYPE_CHECKING:
    from je_auto_control.utils.remote_desktop.webrtc_host import WebRTCDesktopHost
    from je_auto_control.utils.remote_desktop.webrtc_viewer import WebRTCDesktopViewer


async def _wait_steps(*steps: Coroutine[Any, Any, object]) -> None:
    results = await asyncio.gather(*steps, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result


def _being_cancelled() -> bool:
    """Whether the running task itself has a pending cancellation (not just a child's)."""
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


async def _cancel_task(task: asyncio.Task[Any]) -> None:
    """Cancel ``task`` and wait for it; a cancellation of the caller itself still propagates.

    ``except CancelledError: pass`` alone also swallowed the caller's own
    cancellation when it arrived during the wait.
    """
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        if _being_cancelled():
            raise


async def _close_peer(owner: WebRTCDesktopHost | WebRTCDesktopViewer,
                      attempt: CleanupAttempt) -> None:
    peer = owner._pc
    if attempt.run(lambda: close_file_receiver(owner._files_receiver, owner._files_channel), "files"):
        owner._files_receiver = owner._files_channel = None
    if peer is not None and await attempt.wait(peer.close, "peer"):
        if owner._pc is peer:
            owner._pc = None
    if owner._pc is None:
        owner._control_channel = owner._mic_channel = None


async def _host_tasks(owner: WebRTCDesktopHost, attempt: CleanupAttempt) -> None:
    await owner._media_owners.retire_slot("viewer video task", attempt)
    if owner._viewer_video_task is not None:
        task = owner._viewer_video_task
        if await attempt.wait(lambda: _cancel_task(task), "viewer video task") or task.done():
            owner._viewer_video_task = None
            owner._media_owners.settled("viewer video task")


async def _viewer_tasks(owner: WebRTCDesktopViewer, attempt: CleanupAttempt) -> None:
    if owner._receive_task is not None:
        task = owner._receive_task
        if await attempt.wait(lambda: _cancel_task(task), "receive task") or task.done():
            owner._receive_task = None


async def _retire_media(current: Callable[[], Resource | None], clear: Callable[[], None], label: str,
                        owners: PeerMediaOwners, attempt: CleanupAttempt) -> None:
    await owners.retire_slot(label, attempt)
    lock = owners.operation_lock(label)
    if not lock.acquire(blocking=False):
        owners.pending(label)
        attempt.pending.append(label)
        return
    try:
        resource = current()
        if resource is None:
            owners.settled(label)
            clear()
            return
        if not isinstance(resource, AsyncMediaStop):
            def stop_sync() -> None:
                owners.stop_field(label, resource)
            if attempt.run(stop_sync, label) and current() is resource:
                clear()
            return
    finally:
        lock.release()
    await _retire_async_media(resource, current, clear, label, owners, attempt)


async def _retire_async_media(resource: Resource, current: Callable[[], Resource | None],
                              clear: Callable[[], None], label: str,
                              owners: PeerMediaOwners, attempt: CleanupAttempt) -> None:
    async def stop() -> None:
        await owners.stop_field_async(label, resource)
    if not await attempt.wait(stop, label):
        return
    lock = owners.operation_lock(label)
    if not lock.acquire(blocking=False):
        owners.pending(label)
        attempt.pending.append(label)
        return
    try:
        if current() is resource:
            clear()
    finally:
        lock.release()


async def _host_media(owner: WebRTCDesktopHost, attempt: CleanupAttempt) -> None:
    owners = owner._media_owners
    await asyncio.gather(
        _retire_media(lambda: owner._host_voice_track, lambda: setattr(owner, "_host_voice_track", None),
                      "host voice", owners, attempt),
        _retire_media(lambda: owner._opus_audio_receiver, lambda: setattr(owner, "_opus_audio_receiver", None),
                      "opus receiver", owners, attempt),
        _retire_media(lambda: owner._mic_receiver, lambda: setattr(owner, "_mic_receiver", None),
                      "mic receiver", owners, attempt),
        _retire_media(lambda: owner._video_track if owner._external_video_track is None else None,
                      lambda: setattr(owner, "_video_track", None), "screen track", owners, attempt),
    )


async def _viewer_media(owner: WebRTCDesktopViewer, attempt: CleanupAttempt) -> None:
    owners = owner._media_owners
    await asyncio.gather(
        _retire_media(lambda: owner._host_voice_receiver, lambda: setattr(owner, "_host_voice_receiver", None),
                      "host voice", owners, attempt),
        _retire_media(lambda: owner._opus_audio_track, lambda: setattr(owner, "_opus_audio_track", None),
                      "opus mic track", owners, attempt),
        _retire_media(lambda: owner._mic_sender, lambda: setattr(owner, "_mic_sender", None),
                      "mic sender", owners, attempt),
        _retire_media(lambda: owner._viewer_screen_track, lambda: setattr(owner, "_viewer_screen_track", None),
                      "screen track", owners, attempt),
    )


async def stop_host(owner: WebRTCDesktopHost) -> None:
    owner._closed.set()
    owner._authenticated = owner._has_pending_viewer = False
    attempt = CleanupAttempt()
    attempt.run(owner._release_usb_claims, "USB claims")
    if owner._auth_deadline_handle is not None:
        owner._auth_deadline_handle.cancel()
        owner._auth_deadline_handle = None
    await _wait_steps(
        _close_peer(owner, attempt), _host_tasks(owner, attempt), _host_media(owner, attempt),
        owner._media_owners.retire_orphans(attempt),
        attempt.wait(lambda: cancel_file_requests(owner._background_tasks), "file requests"),
    )
    attempt.finish()


async def stop_viewer(owner: WebRTCDesktopViewer) -> None:
    owner._closed.set()
    owner._authenticated = False
    attempt = CleanupAttempt()
    await _wait_steps(_close_peer(owner, attempt), _viewer_tasks(owner, attempt),
                      _viewer_media(owner, attempt), owner._media_owners.retire_orphans(attempt))
    attempt.finish()
