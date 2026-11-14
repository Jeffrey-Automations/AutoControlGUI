"""WebRTC viewer: receives screen video and sends input to the host.

Pair with :class:`WebRTCDesktopHost`. The viewer is offer-consumer: caller
takes the host's offer SDP, calls :meth:`process_offer` to get an answer
SDP, ships it back out-of-band, then drives input via :meth:`send_input`.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Mapping, Optional

from je_auto_control.utils.remote_desktop.webrtc_media_owners import MediaFailure, PeerMediaOwners
from je_auto_control.utils.remote_desktop.media_retirement import raise_cleanup_failures
from je_auto_control.utils.remote_desktop.webrtc_peer_cleanup import stop_viewer
from je_auto_control.utils.remote_desktop.webrtc_retirement import (
    PeerRetirement, PeerStopFailed, stop_resource,
)
from je_auto_control.utils.exception.control_signals import raise_caused_run_interruption
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.remote_desktop.webrtc_file_callbacks import (
    FileReceiveCallbacks, ReceiptCallback,
)
from je_auto_control.utils.remote_desktop.webrtc_file_receive import (
    abort_file_receiver, bind_file_receiver, close_file_receiver,
)
from je_auto_control.utils.remote_desktop.webrtc_transport import (
    RTCPeerConnection, RTCSessionDescription, WebRTCConfig,
    get_bridge, wait_for_ice_gathering,
)

if TYPE_CHECKING:  # imported lazily at runtime to keep startup cheap
    from je_auto_control.utils.remote_desktop.webrtc_audio import (
        OpusMicAudioTrack, OpusMicReceiver,
    )
    from je_auto_control.utils.remote_desktop.webrtc_files import (
        FileTransferReceiver,
    )
    from je_auto_control.utils.remote_desktop.webrtc_mic import MicUplinkSender
    from je_auto_control.utils.remote_desktop.webrtc_transport import (
        ScreenVideoTrack,
    )
    from je_auto_control.utils.usb.passthrough import UsbChannelClient


_OFFER_TIMEOUT_S = 12.0


FrameCallback = Callable[["object"], None]
StateCallback = Callable[[str], None]
AuthCallback = Callable[[bool], None]
FingerprintCallback = Callable[[str], None]
InboxListingCallback = Callable[[list], None]
InboxOpResultCallback = Callable[[str, bool, Optional[str]], None]
FileReceivedCallback = Callable[[Any], None]


class WebRTCDesktopViewer:
    """Single-host viewer with manual SDP exchange.

    ``on_frame(av_frame)`` fires on the asyncio thread every time a video
    frame lands. The GUI side converts the frame to ``QImage`` and emits a
    Qt signal so the actual paint happens on the Qt thread.
    """

    def __init__(self, *, token: str,
                 config: Optional[WebRTCConfig] = None,
                 viewer_id: Optional[str] = None,
                 on_frame: Optional[FrameCallback] = None,
                 on_state_change: Optional[StateCallback] = None,
                 on_auth_result: Optional[AuthCallback] = None,
                 on_fingerprint: Optional[FingerprintCallback] = None) -> None:
        if not token:
            raise ValueError("WebRTC viewer requires a non-empty token")
        self._token = token
        self._config = config or WebRTCConfig()
        self._viewer_id = viewer_id
        self._on_frame = on_frame
        self._on_state_change = on_state_change
        self._on_auth_result = on_auth_result
        self._on_fingerprint = on_fingerprint
        self._pc: Optional[RTCPeerConnection] = None
        self._control_channel: Any = None
        self._mic_channel: Any = None
        self._mic_sender: Optional[MicUplinkSender] = None
        self._files_channel: Any = None
        self._files_receiver: Optional[FileTransferReceiver] = None
        self._usb_channel: Any = None
        self._usb_client: Optional[UsbChannelClient] = None
        self._file_callbacks = FileReceiveCallbacks()
        self._on_inbox_listing: Optional[InboxListingCallback] = None
        self._on_inbox_op_result: Optional[InboxOpResultCallback] = None
        self._viewer_screen_track: Optional[ScreenVideoTrack] = None
        self._opus_audio_track: Optional[OpusMicAudioTrack] = None
        self._host_voice_receiver: Optional[OpusMicReceiver] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._authenticated = False
        self._read_only = False
        self._host_fingerprint: Optional[str] = None
        self._retirement = PeerRetirement()
        self._media_owners = PeerMediaOwners()
        self._closed = threading.Event()
        # Pin fire-and-forget asyncio tasks so they aren't reaped before
        # they finish (S7502). Tasks self-discard via a done callback.
        self._background_tasks: set = set()

    def _require_pc(self) -> RTCPeerConnection:
        """Return the live peer connection, or raise if there isn't one yet."""
        pc = self._pc
        if pc is None:
            raise RuntimeError("viewer has no peer connection; connect first")
        return pc

    def _spawn_bg(self, coro) -> "asyncio.Task":
        task = asyncio.ensure_future(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    # --- public sync API ----------------------------------------------------

    def process_offer(self, offer_sdp: str,
                      expected_dtls_fingerprint: Optional[str] = None) -> str:
        """Apply host offer, build & return answer SDP (with ICE).

        If ``expected_dtls_fingerprint`` is provided, the offer's
        ``a=fingerprint`` line must match before any DTLS handshake; raises
        :class:`FingerprintMismatchError` otherwise (catches a hijacked
        signaling slot before encrypted bytes flow).
        """
        if not offer_sdp or not offer_sdp.strip():
            raise ValueError("offer_sdp is empty")
        if expected_dtls_fingerprint:
            from je_auto_control.utils.remote_desktop.fingerprint import (
                verify_dtls_fingerprint,
            )
            verify_dtls_fingerprint(offer_sdp, expected_dtls_fingerprint)
        self._retirement.require_startable()
        self._retirement.admit_start()
        future = get_bridge().submit(self._async_process_offer(offer_sdp))
        return future.result(timeout=_OFFER_TIMEOUT_S)

    def send_input(self, payload: Mapping[str, Any]) -> None:
        """Send an input dict to the host (mouse/keyboard event)."""
        self._send({"type": "input", "payload": dict(payload)})

    def request_send_sas(self) -> None:
        """Ask the host to fire Ctrl+Alt+Del (Windows-only at the host)."""
        self._send({"type": "send_sas"})

    def enable_mic_send(self) -> None:
        """Start streaming local microphone PCM to the host."""
        from je_auto_control.utils.remote_desktop.webrtc_mic import MicUplinkSender
        with self._media_owners.operation_lock("mic sender"):
            self._media_owners.require_available("mic sender")
            if self._closed.is_set():
                raise PeerStopFailed("peer is stopping")
            if self._mic_sender is not None:
                return
            if self._mic_channel is None:
                raise PeerStopFailed("mic channel not open yet; connect first")
            self._mic_sender = self._media_owners.create(
                "mic sender", lambda: MicUplinkSender(self._mic_channel))
            if self._mic_sender is not None:
                self._media_owners.activate("mic sender", self._mic_sender.start, self._mic_sender,
                                            admitted=lambda: not self._closed.is_set())

    def disable_mic_send(self) -> None:
        with self._media_owners.operation_lock("mic sender"):
            self._media_owners.stop_field("mic sender", self._mic_sender)
            self._mic_sender = None

    @property
    def mic_active(self) -> bool:
        return self._mic_sender is not None and self._mic_sender.is_running()

    def send_file(self, local_path, remote_name: Optional[str] = None,
                  on_progress: Optional[Callable[[int, int], None]] = None, *,
                  cancelled: Optional[Callable[[], bool]] = None, require_commit: bool = False) -> None:
        """Stream to the host inbox, optionally requiring its matching atomic-publication receipt."""
        if self._files_channel is None:
            raise RuntimeError("files channel not open yet")
        from je_auto_control.utils.remote_desktop.webrtc_files import (
            FileTransferSender,
        )
        FileTransferSender(self._files_channel).send(
            local_path, remote_name=remote_name, on_progress=on_progress, cancelled=cancelled,
            require_commit=require_commit,
        )

    def set_file_received_callback(self, callback) -> None:
        """Register ``cb(path)`` for files the host pushes to the viewer."""
        self._file_callbacks.on_file = callback

    def set_file_receipt_callback(self, callback: Optional[ReceiptCallback]) -> None:
        """Register an inert local publication-receipt listener; None clears it."""
        self._file_callbacks.on_receipt = callback

    def set_inbox_listing_callback(self, callback) -> None:
        """Register ``cb(files: list[dict])`` for list_inbox responses."""
        self._on_inbox_listing = callback

    def set_inbox_op_result_callback(self, callback) -> None:
        """Register ``cb(name: str, ok: bool, error: Optional[str])``."""
        self._on_inbox_op_result = callback

    def request_inbox_listing(self) -> None:
        """Ask the host to send its current inbox file listing."""
        self._send({"type": "list_inbox"})

    def request_inbox_file(self, name: str) -> None:
        """Ask the host to push a specific inbox file via the files channel."""
        if not name:
            raise ValueError("name required")
        self._send({"type": "request_file", "name": name})

    def delete_inbox_file(self, name: str) -> None:
        """Ask the host to delete a file from its inbox."""
        if not name:
            raise ValueError("name required")
        self._send({"type": "delete_inbox_file", "name": name})

    def request_renegotiation(self) -> None:
        """Ask the host to send a fresh offer (so we can attach new tracks)."""
        self._send({"type": "renegotiate_request"})

    def toggle_share_screen(self, enable: bool) -> None:
        """Live-toggle viewer→host screen share.

        OFF path is in-place: ``replaceTrack(None)`` and stop the track,
        keeping the SDP direction so the slot survives. Host's
        ``_consume_viewer_video`` sees a clean ``MediaStreamError`` and
        exits its task, but the transceiver remains.

        ON path always renegotiates: a fresh ``ScreenVideoTrack`` is
        created and the host needs a new ``track`` event to spawn its
        consume task again. Repeated ON/OFF cycles thus cost one
        renegotiation per ON; the OFF side is free.
        """
        if enable:
            self._media_owners.require_available("screen track")
        self._config.share_my_screen = bool(enable)
        if not enable:
            self._inplace_detach_track(kind="video")
            return  # no renegotiation on OFF
        if self._viewer_screen_track is not None:
            return  # already on
        # Need fresh negotiation so host re-spawns its consume task
        self.request_renegotiation()

    def toggle_opus_mic(self, enable: bool) -> None:
        """Live-toggle Opus mic uplink (OFF in-place, ON renegotiates)."""
        if enable:
            self._media_owners.require_available("opus mic track")
        self._config.share_my_audio_opus = bool(enable)
        if not enable:
            self._inplace_detach_track(kind="audio")
            return
        if self._opus_audio_track is not None:
            return
        self.request_renegotiation()

    def _current_media_peer(self, peer: object) -> bool:
        return peer is not None and self._pc is peer and not self._closed.is_set()

    def _inplace_detach_track(self, *, kind: str) -> None:
        """Bind delayed detach to the original peer and track."""
        peer = self._pc
        attr = "_viewer_screen_track" if kind == "video" else "_opus_audio_track"
        track = getattr(self, attr)
        if peer is not None and track is not None:
            get_bridge().call_soon(lambda: self._detach_media_track(peer, attr, track))

    def _detach_media_track(self, peer: RTCPeerConnection, attr: str, track) -> None:
        label = "screen track" if attr == "_viewer_screen_track" else "opus mic track"
        with self._media_owners.operation_lock(label):
            if not self._current_media_peer(peer) or getattr(self, attr) is not track:
                return
            if peer is None:
                return
            kind = "video" if attr == "_viewer_screen_track" else "audio"
            failures = self._detach_sender(peer, kind, track)
            try:
                self._media_owners.stop_field(label, track)
            except BaseException as error:  # reason: retain both outcomes before propagating controls
                failures.append(error)
            if failures:
                self._media_owners.failed(label, failures[0])
                raise_cleanup_failures(failures)
            setattr(self, attr, None)

    @staticmethod
    def _detach_sender(peer, kind: str, track) -> list[BaseException]:
        for transceiver in peer.getTransceivers():
            if transceiver.kind == kind and transceiver.sender.track is track:
                try:
                    transceiver.sender.replaceTrack(None)
                except BaseException as error:  # reason: stop the original track before propagating detach failure
                    return [error]
                break
        return []

    def _async_handle_renegotiate(self, offer_sdp: str) -> Coroutine[Any, Any, None]:
        return self._handle_renegotiate(self._pc, offer_sdp)

    async def _handle_renegotiate(self, peer, offer_sdp: str) -> None:
        """Apply the offer only to its original peer generation."""
        if self._pc is not peer:
            return
        async with self._retirement.starting():
            if peer is None or not self._current_media_peer(peer):
                return
            try:
                await peer.setRemoteDescription(
                    RTCSessionDescription(sdp=offer_sdp, type="offer"),
                )
                if not self._current_media_peer(peer):
                    return
                self._attach_optional_tracks()
                answer = await peer.createAnswer()
                await peer.setLocalDescription(answer)
                await wait_for_ice_gathering(peer)
            except (RuntimeError, OSError) as error:
                raise_caused_run_interruption(error)
                autocontrol_logger.warning("renegotiate handle: %r", error)
                return
            if not self._current_media_peer(peer):
                return
            self._send({
                "type": "renegotiate_answer",
                "sdp": peer.localDescription.sdp,
            })
            autocontrol_logger.info("webrtc viewer: sent renegotiate answer")

    def _wire_files_channel(self, channel) -> None:
        from je_auto_control.utils.remote_desktop.webrtc_files import FileTransferReceiver
        close_file_receiver(self._files_receiver, self._files_channel)
        receiver = self._files_receiver = FileTransferReceiver()
        self._files_channel, connection = channel, self._pc

        def active() -> bool:
            return (self._files_channel is channel and self._pc is connection and self._files_receiver is receiver
                    and self._authenticated and not self._closed.is_set())

        bind_file_receiver(channel, receiver, active, self._on_viewer_file_done,
                           received=self._file_callbacks.received)

    def _wire_usb_channel(self, channel) -> None:
        """Attach a USB passthrough client to the ``usb`` DataChannel.

        Exposed via :meth:`usb_client` so the GUI can drive
        ``list_devices`` / ``open`` against the remote host's devices.
        """
        from je_auto_control.utils.usb.passthrough import UsbChannelClient
        self._usb_client = UsbChannelClient(channel)

    def usb_client(self):
        """Return the live USB passthrough client, or None if not wired."""
        return self._usb_client

    def _on_viewer_file_done(self, path) -> None:
        self._file_callbacks.published(path)

    def stop(self) -> None:
        """Wait for software teardown; retain and report unfinished attempts."""
        if self._pc is None and not self._retirement.unsettled and not self._media_owners.unsettled:
            return
        self._closed.set()
        self._authenticated = False
        self._retirement.stop(get_bridge().submit, self._async_stop)

    @property
    def connection_identity(self) -> object:
        """Return an opaque peer-connection identity for delayed work; compare only by object identity."""
        identity: object = self._pc
        return identity

    @property
    def media_failures(self) -> tuple[MediaFailure, ...]:
        """Cached outcomes of unresolved original media owners."""
        return self._media_owners.failures

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    @property
    def read_only(self) -> bool:
        """True if the host has put this session into read-only mode."""
        return self._read_only

    @property
    def host_fingerprint(self) -> Optional[str]:
        """The host's stable fingerprint, available once authenticated."""
        return self._host_fingerprint

    @property
    def connection_state(self) -> str:
        return self._pc.connectionState if self._pc is not None else "closed"

    # --- async internals ----------------------------------------------------

    async def _async_process_offer(self, offer_sdp: str) -> str:
        async with self._retirement.starting():
            return await self._process_offer(offer_sdp)

    async def _process_offer(self, offer_sdp: str) -> str:
        self._media_owners.require_available()
        if self._pc is not None or self._media_owners.unsettled:
            # The whole previous session goes, not only its peer connection:
            # tracks, receivers and the authenticated flag outlived it.
            await self._stop_peer()
        # stop() set this and nothing cleared it, so a reused viewer's video
        # loop ended at once and showed no frames.
        self._retirement.require_startable()
        self._closed.clear()
        self._pc = RTCPeerConnection(
            configuration=self._config.to_rtc_configuration(),
        )
        self._wire_pc_handlers(self._pc)
        offer = RTCSessionDescription(sdp=offer_sdp, type="offer")
        await self._pc.setRemoteDescription(offer)
        self._attach_optional_tracks()
        answer = await self._pc.createAnswer()
        await self._pc.setLocalDescription(answer)
        await wait_for_ice_gathering(self._pc)
        return self._pc.localDescription.sdp

    def _attach_optional_tracks(self) -> None:
        if self._config.share_my_screen and self._viewer_screen_track is None:
            self._attach_viewer_screen_track()
        if self._config.share_my_audio_opus and self._opus_audio_track is None:
            self._attach_opus_audio_track()

    def _attach_viewer_screen_track(self) -> None:
        """Attach our screen to the host's recvonly video slot.

        After ``setRemoteDescription``, aiortc gives every answerer
        transceiver the default ``recvonly`` direction regardless of what
        the remote requested, so we can't filter by direction. Instead we
        rely on m-line order: the second video transceiver corresponds to
        the host's recvonly slot (the first is its outbound screen).
        """
        from je_auto_control.utils.remote_desktop.webrtc_transport import (
            ScreenVideoTrack,
        )
        self._media_owners.require_available("screen track")
        if self._viewer_screen_track is not None:
            return
        video_transceivers = [
            t for t in self._require_pc().getTransceivers() if t.kind == "video"
        ]
        if len(video_transceivers) < 2:
            autocontrol_logger.warning(
                "viewer share_my_screen: host did not advertise a second "
                "video slot (set accept_viewer_video=True on the host)",
            )
            return
        target = video_transceivers[1]
        track = self._media_owners.create("screen track", lambda: ScreenVideoTrack(
            monitor_index=self._config.monitor_index,
            fps=self._config.fps,
            region=self._config.region,
            show_cursor=self._config.show_cursor,
        ), optional=False)
        self._viewer_screen_track = track
        target.sender.replaceTrack(track)
        target.direction = "sendonly"

    def _attach_opus_audio_track(self) -> None:
        """Attach an Opus mic track to the host's recvonly audio slot."""
        from je_auto_control.utils.remote_desktop.webrtc_audio import (
            OpusMicAudioTrack,
        )
        audio_transceivers = [
            t for t in self._require_pc().getTransceivers() if t.kind == "audio"
        ]
        if not audio_transceivers:
            autocontrol_logger.warning(
                "viewer share_my_audio_opus: host did not advertise an audio "
                "slot (set accept_viewer_audio_opus=True on the host)",
            )
            return
        target = audio_transceivers[0]
        self._media_owners.require_available("opus mic track")
        if self._opus_audio_track is not None:
            return
        track = self._media_owners.create("opus mic track", OpusMicAudioTrack)
        if track is None:
            return
        self._opus_audio_track = track
        target.sender.replaceTrack(track)
        target.direction = "sendonly"

    _stop_quietly = staticmethod(stop_resource)

    def _async_stop(self) -> Coroutine[Any, Any, None]:
        return self._stop_generation(self._pc)

    async def _stop_generation(self, peer: object) -> None:
        await self._retirement.retire(peer, lambda: self._pc, self._stop_peer)

    async def _stop_peer(self) -> None:
        await stop_viewer(self)

    # --- wiring -------------------------------------------------------------

    def _wire_pc_handlers(self, pc: RTCPeerConnection) -> None:
        cb = self._on_state_change

        @pc.on("connectionstatechange")
        async def _on_state() -> None:
            current = self._pc
            if current is None or current is not pc:
                return
            state = current.connectionState
            autocontrol_logger.info("webrtc viewer: connection %s", state)
            if state in ("failed", "closed", "disconnected"):
                self._authenticated = False
                close_file_receiver(self._files_receiver, self._files_channel)
            if cb is not None:
                try:
                    cb(state)
                except (RuntimeError, OSError) as error:
                    raise_caused_run_interruption(error)
                    autocontrol_logger.warning("state cb: %r", error)

        @pc.on("track")
        def _on_track(track) -> None:
            if self._pc is not pc or self._closed.is_set():
                return
            autocontrol_logger.info("webrtc viewer: got %s track", track.kind)
            if track.kind == "video":
                self._receive_task = asyncio.ensure_future(
                    self._consume_video(track),
                )
            elif track.kind == "audio":
                self._start_host_voice_play(track)

        @pc.on("datachannel")
        def _on_datachannel(channel) -> None:
            if self._pc is not pc or self._closed.is_set():
                return
            self._attach_datachannel(channel)

    def _attach_datachannel(self, channel) -> None:
        """Route an inbound data channel to its handler by label."""
        autocontrol_logger.info(
            "webrtc viewer: data channel %r open", channel.label,
        )
        if channel.label == "mic":
            self._mic_channel = channel
            return
        if channel.label == "files":
            self._files_channel = channel
            self._wire_files_channel(channel)
            return
        if channel.label == "usb":
            self._usb_channel = channel
            self._wire_usb_channel(channel)
            return
        self._control_channel = channel
        self._wire_control_channel(channel)

    def _wire_control_channel(self, channel) -> None:
        @channel.on("open")
        def _on_open() -> None:
            self._send_auth()

        @channel.on("message")
        def _on_message(message) -> None:
            if self._control_channel is channel:
                self._handle_ctrl_message(message)

        @channel.on("close")
        def _on_close() -> None:
            if self._control_channel is channel:
                self._authenticated = False
                abort_file_receiver(self._files_receiver, self._files_channel)

        # Channel may already be open by the time aiortc fires the
        # "datachannel" event; in that case "open" never fires again.
        if getattr(channel, "readyState", "") == "open":
            self._send_auth()

    def _start_host_voice_play(self, track) -> None:
        from je_auto_control.utils.remote_desktop.webrtc_audio import (
            OpusMicReceiver,
        )
        self._media_owners.require_available("host voice")
        if self._host_voice_receiver is not None:
            return
        receiver = self._media_owners.create("host voice", OpusMicReceiver)
        if receiver is None:
            return
        self._host_voice_receiver = receiver
        self._media_owners.activate("host voice", lambda: receiver.consume(track), receiver)
        autocontrol_logger.info("webrtc viewer: playing host voice")

    async def _consume_video(self, track) -> None:
        # CancelledError is intentionally not caught — it must propagate
        # so the awaiter knows the consumer ended via cancellation
        # rather than a stream error (S7497).
        #
        # MediaStreamError is the *normal* end: aiortc raises it from recv()
        # when the host stops sharing or the connection closes. It derives
        # straight from Exception, so it is not covered by the OSError /
        # RuntimeError arm below, and nobody awaits this task — letting it
        # escape turns every clean disconnect into an un-retrieved task
        # exception. The host's own drain loop has always caught it.
        from aiortc.mediastreams import MediaStreamError
        try:
            while not self._closed.is_set():
                frame = await track.recv()
                if self._on_frame is not None:
                    try:
                        self._on_frame(frame)
                    except (RuntimeError, OSError) as error:
                        autocontrol_logger.debug("frame cb: %r", error)
        except MediaStreamError:
            autocontrol_logger.info("webrtc viewer: video stream ended")
        except (OSError, RuntimeError) as error:
            autocontrol_logger.info("webrtc viewer: video stream ended: %r", error)

    def _send_auth(self) -> None:
        payload = {"type": "auth", "token": self._token}
        if self._viewer_id:
            payload["viewer_id"] = self._viewer_id
        self._send(payload)

    def _handle_ctrl_message(self, message: Any) -> None:
        if self._closed.is_set():
            return
        if not isinstance(message, str):
            return
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return
        msg_type = data.get("type")
        handler = self._ctrl_dispatch.get(msg_type)
        if handler is not None:
            handler(data)
        elif msg_type in ("delete_inbox_response", "request_file_response"):
            self._handle_inbox_op_result(data)

    @property
    def _ctrl_dispatch(self) -> dict:
        return {
            "auth_ok": self._handle_auth_ok,
            "auth_fail": self._handle_auth_fail,
            "read_only": self._handle_read_only_msg,
            "permissions": self._handle_permissions_msg,
            "list_inbox_response": self._handle_list_inbox_response,
            "renegotiate_offer": self._handle_renegotiate_offer,
        }

    def _handle_auth_ok(self, data: dict) -> None:
        self._authenticated = True
        self._read_only = bool(data.get("read_only", False))
        fingerprint = data.get("fingerprint")
        if isinstance(fingerprint, str) and fingerprint:
            self._host_fingerprint = fingerprint
            if self._on_fingerprint is not None:
                try:
                    self._on_fingerprint(fingerprint)
                except (RuntimeError, OSError) as error:
                    autocontrol_logger.debug("fingerprint cb: %r", error)
        self._fire_auth_result(True)

    def _handle_auth_fail(self, _data: dict) -> None:
        self._authenticated = False
        self._fire_auth_result(False)

    def _handle_read_only_msg(self, data: dict) -> None:
        self._read_only = bool(data.get("value", False))

    def _handle_permissions_msg(self, data: dict) -> None:
        value = data.get("value")
        if isinstance(value, dict):
            self._read_only = not bool(value.get("allow_input", True))

    def _handle_list_inbox_response(self, data: dict) -> None:
        if self._on_inbox_listing is None:
            return
        files = data.get("files") or []
        try:
            self._on_inbox_listing(files)
        except (RuntimeError, OSError) as error:
            autocontrol_logger.debug("inbox listing cb: %r", error)

    def _handle_renegotiate_offer(self, data: dict) -> None:
        sdp = data.get("sdp")
        if isinstance(sdp, str) and self._pc is not None:
            self._spawn_bg(self._async_handle_renegotiate(sdp))

    def _handle_inbox_op_result(self, data: dict) -> None:
        if self._on_inbox_op_result is None:
            return
        try:
            self._on_inbox_op_result(
                str(data.get("name", "")),
                bool(data.get("ok", False)),
                data.get("error"),
            )
        except (RuntimeError, OSError) as error:
            autocontrol_logger.debug("inbox op cb: %r", error)

    def _fire_auth_result(self, ok: bool) -> None:
        if self._on_auth_result is None:
            return
        try:
            self._on_auth_result(ok)
        except (RuntimeError, OSError) as error:
            autocontrol_logger.warning("auth cb: %r", error)

    def _send(self, payload: Mapping[str, Any]) -> None:
        if self._control_channel is None:
            autocontrol_logger.debug("viewer send before channel open")
            return
        text = json.dumps(payload)
        get_bridge().call_soon(self._safe_channel_send, text)

    def _safe_channel_send(self, text: str) -> None:
        if self._control_channel is None:
            return
        try:
            self._control_channel.send(text)
        except (RuntimeError, OSError) as error:
            autocontrol_logger.warning("ctrl send: %r", error)


__all__ = ["WebRTCDesktopViewer"]
