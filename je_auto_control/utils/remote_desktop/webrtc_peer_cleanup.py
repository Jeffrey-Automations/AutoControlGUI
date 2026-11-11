"""Software cleanup of a serialized peer generation, retaining failed resources."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Coroutine

from je_auto_control.utils.remote_desktop.webrtc_file_receive import close_file_receiver
from je_auto_control.utils.remote_desktop.webrtc_file_tasks import cancel_file_requests
from je_auto_control.utils.remote_desktop.webrtc_retirement import CleanupAttempt

if TYPE_CHECKING:
    from je_auto_control.utils.remote_desktop.webrtc_host import WebRTCDesktopHost
    from je_auto_control.utils.remote_desktop.webrtc_viewer import WebRTCDesktopViewer


async def _wait_steps(*steps: Coroutine[Any, Any, object]) -> None:
    results = await asyncio.gather(*steps, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result


async def _cancel_task(task: asyncio.Task[Any]) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


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
    if owner._viewer_video_task is not None:
        task = owner._viewer_video_task
        if await attempt.wait(lambda: _cancel_task(task), "viewer video task") or task.done():
            owner._viewer_video_task = None


async def _viewer_tasks(owner: WebRTCDesktopViewer, attempt: CleanupAttempt) -> None:
    if owner._receive_task is not None:
        task = owner._receive_task
        if await attempt.wait(lambda: _cancel_task(task), "receive task") or task.done():
            owner._receive_task = None


async def stop_host(owner: WebRTCDesktopHost) -> None:
    owner._closed.set()
    owner._authenticated = owner._has_pending_viewer = False
    attempt = CleanupAttempt()
    owner._host_voice_track = attempt.stop(owner._host_voice_track, "host voice")
    owner._opus_audio_receiver = attempt.stop(owner._opus_audio_receiver, "opus receiver")
    owner._mic_receiver = attempt.stop(owner._mic_receiver, "mic receiver")
    if owner._external_video_track is None:
        owner._video_track = attempt.stop(owner._video_track, "screen track")
    else:
        owner._video_track = None
    attempt.run(owner._release_usb_claims, "USB claims")
    if owner._auth_deadline_handle is not None:
        owner._auth_deadline_handle.cancel()
        owner._auth_deadline_handle = None
    await _wait_steps(
        _close_peer(owner, attempt), _host_tasks(owner, attempt),
        attempt.wait(lambda: cancel_file_requests(owner._background_tasks), "file requests"),
    )
    attempt.finish()


async def stop_viewer(owner: WebRTCDesktopViewer) -> None:
    owner._closed.set()
    owner._authenticated = False
    attempt = CleanupAttempt()
    owner._host_voice_receiver = attempt.stop(owner._host_voice_receiver, "host voice")
    owner._opus_audio_track = attempt.stop(owner._opus_audio_track, "opus mic track")
    owner._viewer_screen_track = attempt.stop(owner._viewer_screen_track, "screen track")
    owner._mic_sender = attempt.stop(owner._mic_sender, "mic sender")
    await _wait_steps(_close_peer(owner, attempt), _viewer_tasks(owner, attempt))
    attempt.finish()
