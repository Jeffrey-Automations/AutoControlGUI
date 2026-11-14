"""Renegotiation and recvonly-track management for the WebRTC host.

aiortc has no ``removeTransceiver``, so turning viewer video or Opus audio
on and off is not symmetric: enabling adds a recvonly transceiver and
re-offers, disabling can only set the existing one inactive and stop the
receiver. That asymmetry, the host-initiated offer that carries it, and the
re-subscription that runs after each answer are the whole of this mixin.
"""
from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Mapping, Optional

from je_auto_control.utils.exception.control_signals import raise_caused_run_interruption
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.remote_desktop.webrtc_media_owners import PeerMediaOwners
from je_auto_control.utils.remote_desktop.webrtc_transport import (
    get_bridge, wait_for_ice_gathering,
)

if TYPE_CHECKING:  # imported lazily at runtime to keep startup cheap
    from je_auto_control.utils.remote_desktop.webrtc_audio import OpusMicReceiver, OpusMicAudioTrack
    from je_auto_control.utils.remote_desktop.webrtc_transport import (
        RTCPeerConnection, WebRTCConfig,
    )



def _being_cancelled() -> bool:
    """Whether the running task itself has a pending cancellation (not just a child's)."""
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0

class MediaNegotiationMixin:
    """Media-track half of :class:`WebRTCDesktopHost`.

    Requires the host to provide ``_pc``, ``_config``, ``_viewer_video_task``,
    ``_opus_audio_receiver``, ``_send_ctrl``, ``_spawn_bg``,
    ``_consume_viewer_video`` and ``_start_opus_audio_receive``.
    """

    if TYPE_CHECKING:
        # Declared, never defined: the host class this is mixed into owns
        # every one of these. The block is stripped at runtime, so nothing
        # here can shadow what the host actually binds.
        _pc: Optional["RTCPeerConnection"]
        _media_owners: PeerMediaOwners
        _closed: threading.Event
        _host_voice_track: Optional["OpusMicAudioTrack"]
        _config: "WebRTCConfig"
        _viewer_video_task: Optional[asyncio.Task]
        _opus_audio_receiver: Optional["OpusMicReceiver"]
        _send_ctrl: Callable[[Mapping[str, Any]], None]
        _spawn_bg: Callable[[Any], asyncio.Task]
        _consume_viewer_video: Callable[[Any], Coroutine[Any, Any, None]]
        _start_opus_audio_receive: Callable[[Any], None]

    def _attach_host_voice(self) -> None:
        from je_auto_control.utils.remote_desktop.webrtc_audio import OpusMicAudioTrack
        self._media_owners.require_available("host voice")
        if self._host_voice_track is not None or self._pc is None:
            return
        track = self._media_owners.create("host voice", OpusMicAudioTrack)
        if track is not None:
            self._host_voice_track = track
            self._pc.addTrack(track)

    def _current_media_peer(self, peer: object) -> bool:
        return peer is not None and self._pc is peer and not self._closed.is_set()

    def _queue_for_media_peer(self, action: Callable[[], object]) -> None:
        peer = self._pc
        def run() -> None:
            if peer is not None and self._pc is peer and not self._closed.is_set():
                action()
        get_bridge().call_soon(run)

    def _maybe_resubscribe_viewer_video(self) -> None:
        if not (self._config.accept_viewer_video
                and self._viewer_video_task is None
                and self._pc is not None):
            return
        video_ts = [
            t for t in self._pc.getTransceivers() if t.kind == "video"
        ]
        for transceiver in video_ts[1:]:  # skip our outbound slot
            track = self._receiver_track(transceiver)
            if track is None:
                continue
            self._viewer_video_task = self._spawn_bg(
                self._consume_viewer_video(track),
            )
            autocontrol_logger.info(
                "webrtc host: re-spawned viewer video consume task",
            )
            return

    def _maybe_resubscribe_viewer_audio(self) -> None:
        if not (self._config.accept_viewer_audio_opus
                and self._opus_audio_receiver is None
                and self._pc is not None):
            return
        for transceiver in self._pc.getTransceivers():
            if transceiver.kind != "audio":
                continue
            track = self._receiver_track(transceiver)
            if track is None:
                continue
            self._start_opus_audio_receive(track)
            return

    @staticmethod
    def _receiver_track(transceiver):
        receiver = transceiver.receiver
        return receiver.track if receiver is not None else None

    def _async_renegotiate(self) -> Coroutine[Any, Any, None]:
        return self._renegotiate_peer(self._pc)

    async def _renegotiate_peer(self, peer: Optional["RTCPeerConnection"]) -> None:
        if peer is None or not self._current_media_peer(peer):
            return
        try:
            offer = await peer.createOffer()
            if not self._current_media_peer(peer):
                return
            await peer.setLocalDescription(offer)
            await wait_for_ice_gathering(peer)
        except (RuntimeError, OSError) as error:
            raise_caused_run_interruption(error)
            autocontrol_logger.warning("renegotiate offer: %r", error)
            return
        if self._current_media_peer(peer):
            self._send_ctrl({"type": "renegotiate_offer", "sdp": peer.localDescription.sdp})

    def request_renegotiation(self) -> None:
        """Public sync entry: kick off a fresh SDP exchange over ctrl channel."""
        if self._pc is None:
            return
        self._queue_for_media_peer(lambda: self._spawn_bg(self._async_renegotiate()))

    def enable_accept_viewer_video(self) -> None:
        """Live-add a recvonly video transceiver and renegotiate.

        ``enable_*`` only adds capacity — aiortc has no ``removeTransceiver``,
        so disabling needs a reconnect (or set the transceiver to inactive).
        """
        if self._pc is None:
            return
        self._media_owners.require_available("viewer video task")
        self._config.accept_viewer_video = True
        self._queue_for_media_peer(self._add_recvonly_video_and_renegotiate)

    def enable_accept_viewer_audio_opus(self) -> None:
        """Live-add a recvonly audio transceiver and renegotiate."""
        if self._pc is None:
            return
        self._media_owners.require_available("opus receiver")
        self._config.accept_viewer_audio_opus = True
        self._queue_for_media_peer(self._add_recvonly_audio_and_renegotiate)

    def _add_recvonly_video_and_renegotiate(self) -> None:
        if self._pc is None:
            return
        already = sum(
            1 for t in self._pc.getTransceivers() if t.kind == "video"
        )
        if already < 2:
            self._pc.addTransceiver("video", direction="recvonly")
        self._spawn_bg(self._async_renegotiate())

    def _add_recvonly_audio_and_renegotiate(self) -> None:
        if self._pc is None:
            return
        already = sum(
            1 for t in self._pc.getTransceivers() if t.kind == "audio"
        )
        if already < 1:
            self._pc.addTransceiver("audio", direction="recvonly")
        self._spawn_bg(self._async_renegotiate())

    def disable_accept_viewer_video(self) -> None:
        """Mark the recvonly video slot inactive + stop the consume task."""
        if self._pc is None:
            return
        self._config.accept_viewer_video = False
        task = self._viewer_video_task
        self._queue_for_media_peer(
            lambda: self._deactivate_recvonly_video() if self._viewer_video_task is task else None)

    def disable_accept_viewer_audio_opus(self) -> None:
        """Mark the recvonly audio slot inactive + stop the Opus receiver."""
        if self._pc is None:
            return
        self._config.accept_viewer_audio_opus = False
        receiver = self._opus_audio_receiver
        self._queue_for_media_peer(
            lambda: self._deactivate_recvonly_audio() if self._opus_audio_receiver is receiver else None)

    def _deactivate_recvonly_video(self) -> None:
        if self._pc is None:
            return
        # Find the second video transceiver (the recvonly one); first is our
        # outbound screen track.
        video_ts = [t for t in self._pc.getTransceivers() if t.kind == "video"]
        if len(video_ts) >= 2:
            try:
                video_ts[1].direction = "inactive"
            except (RuntimeError, OSError) as error:
                autocontrol_logger.debug("inactivate video: %r", error)
        peer, task = self._pc, self._viewer_video_task
        self._media_owners.schedule("viewer video task", lambda: self._retire_live_video(peer, task))

    def _deactivate_recvonly_audio(self) -> None:
        if self._pc is None:
            return
        audio_ts = [t for t in self._pc.getTransceivers() if t.kind == "audio"]
        if audio_ts:
            # With host voice on, this transceiver also carries the host's
            # own track: only its receiving half is turned off.
            sending = audio_ts[0].sender is not None and audio_ts[0].sender.track is not None
            try:
                audio_ts[0].direction = "sendonly" if sending else "inactive"
            except (RuntimeError, OSError) as error:
                autocontrol_logger.debug("inactivate audio: %r", error)
        peer, receiver = self._pc, self._opus_audio_receiver
        if receiver is None:
            self._spawn_bg(self._async_renegotiate())
            return
        self._media_owners.schedule("opus receiver", lambda: self._retire_live_audio(peer, receiver))

    async def _retire_live_audio(self, peer, receiver) -> None:
        if self._pc is not peer or self._opus_audio_receiver is not receiver:
            return
        await self._media_owners.stop_field_async("opus receiver", receiver)
        if self._opus_audio_receiver is receiver:
            self._opus_audio_receiver = None
        if self._pc is peer and not self._closed.is_set():
            self._spawn_bg(self._async_renegotiate())

    async def _retire_live_video(self, peer, task) -> None:
        if self._pc is not peer or self._viewer_video_task is not task:
            return
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                if _being_cancelled():
                    raise   # this task's own cancellation, not the child's
            finally:
                if task.done() and self._viewer_video_task is task:
                    self._viewer_video_task = None
        self._media_owners.settled("viewer video task")
        if self._pc is peer and not self._closed.is_set():
            self._spawn_bg(self._async_renegotiate())
