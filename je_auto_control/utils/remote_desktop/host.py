"""TCP host that streams JPEG frames and applies viewer input."""
import json
import socket
import ssl
import threading
import time
from functools import partial
from types import TracebackType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.remote_desktop.media_retirement import MediaRetirementError
from je_auto_control.utils.exception.control_signals import raise_caused_run_interruption
from je_auto_control.utils.remote_desktop.audio import (
    AudioCapture, AudioCaptureConfig,
)
from je_auto_control.utils.remote_desktop.auth import (
    verify_response,
)
from je_auto_control.utils.remote_desktop.clipboard_delivery import apply_clipboard
from je_auto_control.utils.remote_desktop.clipboard_sync import (
    encode_image, encode_text,
)
from je_auto_control.utils.remote_desktop.file_transfer import (
    FileReceiver, FileTransferError, ProgressCallback, send_file,
)
from je_auto_control.utils.remote_desktop.host_id import (
    load_or_create_host_id, validate_host_id,
)
from je_auto_control.utils.remote_desktop.input_dispatch import (
    dispatch_input,
)
from je_auto_control.utils.remote_desktop.protocol import (
    MessageType,
)
from je_auto_control.utils.remote_desktop.resume_tokens import (
    ResumeTokenStore,
)
from je_auto_control.utils.remote_desktop.video_codec import (
    CodecProvider, JpegPassthrough,
)
from je_auto_control.utils.remote_desktop.delta_frames import (
    DeltaFrameHistory, KeyframeRequests, history_for_codec,
)
from je_auto_control.utils.remote_desktop.transport import (
    MessageChannel, TcpMessageChannel,
)
from je_auto_control.utils.remote_desktop.host_access import (
    PendingViewerCallback, _candidate_totp_codes, _compile_ip_allowlist,
)
from je_auto_control.utils.remote_desktop.host_admission import (
    DEFAULT_AUTH_TIMEOUT_S, DEFAULT_MAX_PENDING_HANDSHAKES,
    ConnectionAdmissionMixin, PendingAdmission, validate_admission_args,
)
from je_auto_control.utils.remote_desktop.host_capture import (
    CursorProvider, FrameProductionMixin, FrameProvider,
    _DEFAULT_QUALITY, _default_frame_provider,
    _resolve_cursor_provider, _resolve_monitor_region, capture_origin,
)
from je_auto_control.utils.remote_desktop.host_client import (
    _ClientHandler,
)

InputDispatcher = Callable[[Mapping[str, Any]], Any]


def _send_message(msg_type: MessageType, payload: bytes, channel: MessageChannel) -> None:
    """Send one message; the viewer's sender thread handles a broken channel."""
    channel.send_typed(msg_type, payload)


def _send_file_logged(address: Tuple[Any, ...], source_path: str, dest_path: str,
                      on_progress: Optional[ProgressCallback], channel: MessageChannel) -> None:
    """Stream one file to one viewer; a failure is logged and keeps the viewer connected."""
    try:
        send_file(channel, source_path, dest_path, on_progress=on_progress)
    except (OSError, FileTransferError) as error:
        autocontrol_logger.info("remote_desktop file send to %s failed: %r", address, error)
# accept() 的輪詢間隔，用來定期檢查 _shutdown 旗標。
# How long accept() blocks before re-checking the _shutdown flag.
_ACCEPT_POLL_TIMEOUT_S = 0.5
_FILE_MSG_TYPES = frozenset({
    MessageType.FILE_BEGIN, MessageType.FILE_CHUNK, MessageType.FILE_END,
})


def _validate_host_args(token: str, fps: float, quality: int) -> None:
    """Throw early on bad constructor args so the host never starts broken."""
    if not isinstance(token, str) or not token:
        raise ValueError("token must be a non-empty string")
    if fps <= 0:
        raise ValueError("fps must be positive")
    if not 1 <= quality <= 95:
        raise ValueError("quality must be in [1, 95]")


class RemoteDesktopHost(ConnectionAdmissionMixin, FrameProductionMixin):
    """Stream the screen to authenticated viewers and apply their input.

    The instance owns three kinds of threads: one accept loop, one
    capture loop, and a sender + receiver pair per connected viewer.
    Public methods are thread-safe; ``start()`` is idempotent and
    ``stop()`` can be called from any thread.

    A connection that has not yet proved its credentials does not take one
    of the ``max_clients`` viewer slots: at most ``max_pending_handshakes``
    (default 8) connections may be authenticating at once, more are closed
    at accept, and each must authenticate within ``auth_timeout`` seconds
    (default 10, at most 60) of being accepted, TLS and WebSocket upgrade
    included. The host's approval callback then has the rest of the
    60-second handshake bound, while the viewer holds a viewer slot.
    """

    def __init__(
            # Each kwarg is a documented public knob; bundling them would split
            # the API across patterns and force every caller (registry,
            # host_panel, tests in 8 files) through a wrapper object.
            self, token: str,  # NOSONAR python:S107  # reason: see above
            bind: str = "127.0.0.1",
            port: int = 0,
            fps: float = 10.0,
            quality: int = _DEFAULT_QUALITY,
            region: Optional[Sequence[int]] = None,
            max_clients: int = 4,
            frame_provider: Optional[FrameProvider] = None,
            input_dispatcher: Optional[InputDispatcher] = None,
            host_id: Optional[str] = None,
            ssl_context: Optional[ssl.SSLContext] = None,
            audio_config: Optional[AudioCaptureConfig] = None,
            audio_capture: Optional[Any] = None,
            on_pending_viewer: Optional[PendingViewerCallback] = None,
            cursor_provider: Optional[CursorProvider] = None,
            enable_cursor_broadcast: bool = True,
            ip_allowlist: Optional[Sequence[str]] = None,
            monitor_index: Optional[int] = None,
            single_use_tokens: Optional[Sequence[str]] = None,
            on_chat: Optional[Callable[[str, str], None]] = None,
            totp_secret: Optional[str] = None,
            codec_provider: Optional[CodecProvider] = None,
            max_pending_handshakes: int = DEFAULT_MAX_PENDING_HANDSHAKES,
            auth_timeout: float = DEFAULT_AUTH_TIMEOUT_S,
            ) -> None:
        _validate_host_args(token, fps, int(quality))
        max_pending_handshakes, auth_timeout = validate_admission_args(max_pending_handshakes, auth_timeout)
        if audio_config is None:
            audio_config = AudioCaptureConfig()
        # Phase 2.1: pick a specific monitor by index if requested and
        # the caller did not pass an explicit region.
        if region is None and monitor_index is not None:
            region = _resolve_monitor_region(monitor_index)
        self._host_id = (validate_host_id(host_id) if host_id
                         else load_or_create_host_id())
        self._token = token
        self._ssl_context = ssl_context
        self._bind = bind
        self._requested_port = int(port)
        self._period = 1.0 / float(fps)
        self._max_clients = int(max_clients)
        self._frame_provider: FrameProvider = (
            frame_provider or _default_frame_provider(region, int(quality))
        )
        # Viewer input and the broadcast cursor are in frame coordinates; the
        # default frame starts at the region's or the virtual desktop's corner.
        origin = capture_origin(region) if frame_provider is None else (0, 0)
        self._dispatch: InputDispatcher = input_dispatcher or partial(dispatch_input, origin=origin)
        self._file_receiver: Optional[FileReceiver] = None
        self._audio_config = audio_config
        self._audio_capture_override = audio_capture
        self._audio_capture: Optional[AudioCapture] = None
        self._on_pending_viewer = on_pending_viewer
        self._cursor_provider: Optional[CursorProvider] = _resolve_cursor_provider(
            cursor_provider, enable_cursor_broadcast, origin,
        )
        self._cursor_thread: Optional[threading.Thread] = None
        # Latest broadcast cursor payload, kept so newly-authenticated
        # clients can be seeded immediately instead of waiting for the
        # next position change.
        self._latest_cursor_payload: Optional[bytes] = None
        self._cursor_lock = threading.Lock()
        # Phase 4.3: parsed allowlist. None means "accept anyone".
        self._ip_allowlist: Optional[List[Any]] = _compile_ip_allowlist(
            ip_allowlist,
        )
        # Phase 4.2: extra tokens that self-destruct after a single
        # successful auth — useful for client-support workflows where
        # the host operator hands out a one-shot code that expires on
        # first use.
        self._single_use_tokens = set(single_use_tokens or ())
        self._single_use_lock = threading.Lock()
        # Phase 5.2: host-side chat callback (sender, text).
        self._on_chat = on_chat
        # Phase 4.1: TOTP secret. None disables 2FA (default).
        self._totp_secret = totp_secret
        # Phase 6.6: in-memory resume tokens — viewer reconnects within
        # the TTL skip the approval popup and re-use the saved permission.
        self._resume_store = ResumeTokenStore()
        # Phase 6.8: pluggable video codec. Default JPEG passthrough
        # keeps the wire format byte-for-byte identical to pre-6.8
        # clients; opt in to H.264 by passing an H264CodecProvider.
        self._codec_provider: CodecProvider = (
            codec_provider if codec_provider is not None else JpegPassthrough()
        )
        # A delta codec's P-frames need the frames before them: such a stream
        # keeps a short backlog, and a viewer that falls further behind waits
        # for a keyframe (asked for, rate-limited) instead of decoding garbage.
        self._delta_history: Optional[DeltaFrameHistory] = history_for_codec(
            self._codec_provider.name)
        self._keyframe_requests = KeyframeRequests()
        self._listen_sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()
        # 保護 start()/stop() 互斥。類別文件承諾「start() 具冪等性、
        # stop() 可從任何執行緒呼叫」，但兩者原本毫無互斥，交錯時
        # stop() 會在 start() 指派與啟動執行緒之間把欄位清成 None。
        # Serialises start() against stop(). The class contract promises
        # "start() is idempotent and stop() can be called from any thread",
        # but nothing enforced it: an interleaved stop() nulls _capture_thread
        # between start()'s assignment and its .start() call. This is the
        # outermost lock — always taken before _clients_lock, never after.
        self._lifecycle_lock = threading.RLock()
        self._clients: List[_ClientHandler] = []
        self._clients_lock = threading.Lock()
        # Connections accepted but not yet authenticated, each with its run's
        # stop event; they hold a pending slot, never a viewer slot.
        self._pending: Dict[PendingAdmission, threading.Event] = {}
        self._max_pending_handshakes = int(max_pending_handshakes)
        self._auth_timeout = float(auth_timeout)
        self._handshake_slots = threading.BoundedSemaphore(self._max_pending_handshakes)
        self._frame_cond = threading.Condition()
        self._latest_frame: Optional[bytes] = None
        self._latest_seq = 0
        self._port: int = 0

    # public API ----------------------------------------------------------

    @property
    def host_id(self) -> str:
        """The 9-digit numeric ID viewers use to verify this host."""
        return self._host_id

    @property
    def audio_enabled(self) -> bool:
        return self._audio_config.enabled and self._audio_capture is not None

    @property
    def port(self) -> int:
        return self._port

    @property
    def is_running(self) -> bool:
        return self._listen_sock is not None and not self._shutdown.is_set()

    @property
    def connected_clients(self) -> int:
        with self._clients_lock:
            return sum(
                1 for client in self._clients
                if client.authenticated and not client._shutdown.is_set()
            )

    def latest_frame(self) -> Optional[bytes]:
        """Return the most recent encoded frame (JPEG bytes) or ``None``.

        Useful for a local preview pane: the GUI can poll this without
        opening a TCP connection back to the host.
        """
        with self._frame_cond:
            return self._latest_frame

    def start(self) -> None:
        """Bind, then launch accept + capture (+ cursor) threads."""
        with self._lifecycle_lock:
            self._start_locked()

    def _start_locked(self) -> None:
        if self.is_running:
            return
        # A fresh event per run, never clear() on the old one: a loop that
        # outlived stop()'s join would see it cleared and resume beside
        # the new run.
        self._shutdown = threading.Event()
        self._resume_store.clear()   # a restart invalidates what the last run issued
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self._bind, self._requested_port))
        sock.listen(self._max_clients)
        # Configure on the owning thread, before publishing the socket: leaving
        # this to the accept thread races a concurrent stop() closing it, which
        # makes settimeout raise WSAENOTSOCK outside any handler.
        sock.settimeout(_ACCEPT_POLL_TIMEOUT_S)
        self._port = sock.getsockname()[1]
        self._listen_sock = sock
        self._accept_thread = threading.Thread(
            target=self._accept_loop, args=(self._shutdown,),
            name="rd-accept", daemon=True,
        )
        self._capture_thread = threading.Thread(
            target=self._capture_loop, args=(self._shutdown,),
            name="rd-capture", daemon=True,
        )
        self._accept_thread.start()
        self._capture_thread.start()
        if self._cursor_provider is not None:
            self._cursor_thread = threading.Thread(
                target=self._cursor_loop, args=(self._shutdown,),
                name="rd-cursor", daemon=True,
            )
            self._cursor_thread.start()
        self._start_audio_capture()

    def stop(self, timeout: float = 2.0) -> None:
        """Tear down accept loop, capture loop, and every connected client."""
        with self._lifecycle_lock:
            self._stop_locked(timeout)

    def _stop_locked(self, timeout: float) -> None:
        if self._listen_sock is None:
            self._stop_audio_capture()
            return
        self._shutdown.set()
        audio_error = None
        try:
            self._stop_audio_capture()
        except BaseException as error:  # NOSONAR  # reason: finish host cleanup; audio failure kept
            audio_error = error
        try:
            self._listen_sock.close()
        except OSError:
            pass
        self._listen_sock = None
        with self._frame_cond:
            self._frame_cond.notify_all()
        self._stop_connections()
        for thread in (self._accept_thread, self._capture_thread,
                       self._cursor_thread):
            # is_alive() also guards the not-yet-started case: start() assigns
            # these attributes before calling start() on them, and stop()'s
            # guard (_listen_sock) is already set by then, so a concurrent
            # stop() can reach a Thread that was never started. join() on one
            # raises RuntimeError and aborts the rest of teardown.
            if thread is not None and thread.is_alive():
                thread.join(timeout=timeout)
        self._accept_thread = None
        self._capture_thread = None
        self._cursor_thread = None
        if audio_error is not None:
            raise_caused_run_interruption(audio_error)
            raise audio_error

    def _stop_connections(self) -> None:
        """Close every connection still authenticating, stop every viewer, abort their uploads."""
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
            pending = list(self._pending)
            self._pending.clear()
        for admission in pending:
            admission.abort()
        for client in clients:
            client.stop()
        if self._file_receiver is not None:
            self._file_receiver.abort_all("host stopped")

    def _start_audio_capture(self) -> None:
        """Open the audio input stream when audio capture is enabled."""
        if self._audio_capture is not None:
            self._stop_audio_capture()
        config = self._audio_config
        if not config.enabled:
            return
        if self._audio_capture_override is not None:
            self._audio_capture = self._audio_capture_override
            try:
                self._audio_capture.start()
            except (OSError, RuntimeError) as error:
                raise_caused_run_interruption(error)
                autocontrol_logger.warning(
                    "remote_desktop audio capture failed to start: %r", error,
                )
                if not isinstance(error, MediaRetirementError):
                    self._audio_capture = None
            return
        try:
            capture = AudioCapture(
                on_block=self._broadcast_audio,
                device=config.device,
                sample_rate=config.sample_rate,
                channels=config.channels,
                block_frames=config.block_frames,
            )
            self._audio_capture = capture
            capture.start()
        except (OSError, RuntimeError) as error:
            raise_caused_run_interruption(error)
            autocontrol_logger.warning(
                "remote_desktop audio capture disabled: %r", error,
            )
            if not isinstance(error, MediaRetirementError):
                self._audio_capture = None
            return
        self._audio_capture = capture

    def _stop_audio_capture(self) -> None:
        capture = self._audio_capture
        if capture is None:
            return
        capture.stop()
        self._audio_capture = None

    def _broadcast_audio(self, chunk: bytes) -> None:
        """Push a captured PCM block to every authenticated client."""
        with self._clients_lock:
            clients = [c for c in self._clients
                       if c.authenticated and not c._shutdown.is_set()]
        for client in clients:
            client.push_audio(chunk)

    def broadcast_clipboard_text(self, text: str, *, automatic: bool = False) -> int:
        """Send a text-clipboard message to every authenticated viewer.

        ``automatic=True`` is for code that forwards clipboard *changes* by
        itself: a viewer is then skipped when this is exactly what that
        viewer just sent, or what it was already sent, so two machines
        watching each other's clipboard settle after one transfer. Without
        it (a person asking) every viewer is sent the text. Returns how many
        viewers it went to.
        """
        return self._broadcast_clipboard_payload(encode_text(text), "text", text, automatic)

    def broadcast_clipboard_image(self, png_bytes: bytes, *, automatic: bool = False) -> int:
        """Send a PNG image to every authenticated viewer's clipboard.

        ``automatic`` as in :meth:`broadcast_clipboard_text`.
        """
        return self._broadcast_clipboard_payload(
            encode_image(png_bytes), "image", bytes(png_bytes), automatic)

    def _live_clients(self) -> List[_ClientHandler]:
        """Snapshot the authenticated viewers that are still connected."""
        with self._clients_lock:
            return [c for c in self._clients
                    if c.authenticated and not c._shutdown.is_set()]

    def _broadcast_clipboard_payload(self, payload: bytes, kind: str, data: Any,
                                     automatic: bool) -> int:
        """Queue a CLIPBOARD on each viewer's own sender; returns how many took it."""
        sent = 0
        for client in self._live_clients():
            # One guard per viewer: what viewer A sent still goes to viewer B.
            if automatic and not client.clipboard_guard.should_send(kind, data):
                continue
            if client.push_outgoing("clipboard", partial(_send_message, MessageType.CLIPBOARD, payload)):
                client.clipboard_guard.note_sent(kind, data)
                sent += 1
        return sent

    def set_file_receiver(self, receiver: FileReceiver) -> None:
        """Replace the default ``FileReceiver`` (e.g. to wire progress callbacks)."""
        self._file_receiver = receiver

    def _ensure_file_receiver(self) -> FileReceiver:
        if self._file_receiver is None:
            self._file_receiver = FileReceiver()
        return self._file_receiver

    def send_file_to_viewers(self, source_path: str, dest_path: str,
                             on_progress: Optional[ProgressCallback] = None) -> int:
        """Stream ``source_path`` to every authenticated viewer.

        ``dest_path`` is relative to each viewer's download directory: a
        viewer refuses an absolute path or one that leaves that directory.

        Returns the number of viewers the transfer was queued for. Each
        viewer's copy runs on that viewer's own sender thread, so one that
        stopped reading holds only itself, and ``on_progress`` is called
        from those threads. Each viewer gets its own ``transfer_id`` so
        progress callbacks can be demultiplexed in the GUI.
        """
        queued = 0
        for client in self._live_clients():
            job = partial(_send_file_logged, client.address, source_path, dest_path, on_progress)
            queued += client.push_outgoing("file", job)
        return queued

    def _try_consume_resume(self, nonce: bytes,
                            payload: bytes) -> Optional[str]:
        """Phase 6.6: find a resume token whose HMAC matches ``payload``.

        Returns the saved permission string and removes the matching
        token from the store. Returns ``None`` when no token in the
        store signed this nonce — caller then falls back to the normal
        ``_verify_token`` path.
        """
        for token in self._resume_store.list_active():
            if verify_response(token, nonce, payload):
                # consume() decides: of two connections that both got here
                # with one token, only the one that removes it resumes.
                return self._resume_store.consume(token)
        return None

    def _verify_token(self, nonce: bytes, payload: bytes) -> bool:
        """Phase 4.2 + 4.1: token / single-use code / TOTP-bound token.

        When ``totp_secret`` is configured the viewer must sign with
        ``token:CODE`` where CODE is the current 6-digit TOTP. We try
        each code in a ±1-step window so a viewer that is just out of
        phase still authenticates.

        Single-use tokens are removed on first successful match so the
        same code never authenticates twice — matches the AnyDesk
        "share code" pattern for client-support flows.
        """
        if self._totp_secret is None:
            if verify_response(self._token, nonce, payload):
                return True
        else:
            for code in _candidate_totp_codes(self._totp_secret):
                if verify_response(
                        f"{self._token}:{code}", nonce, payload,
                ):
                    return True
        with self._single_use_lock:
            # No list() copy needed: ``return True`` exits before the
            # mutation could affect a subsequent iteration step.
            for code in self._single_use_tokens:
                if verify_response(code, nonce, payload):
                    self._single_use_tokens.discard(code)
                    return True
        return False

    def add_single_use_token(self, code: str) -> None:
        """Register an extra token that's consumed on first successful auth."""
        if not isinstance(code, str) or not code:
            raise ValueError("share code must be a non-empty string")
        with self._single_use_lock:
            self._single_use_tokens.add(code)

    def revoke_single_use_token(self, code: str) -> bool:
        """Remove a share code before it's used; returns True if found."""
        with self._single_use_lock:
            if code in self._single_use_tokens:
                self._single_use_tokens.discard(code)
                return True
        return False

    def _apply_clipboard(self, kind: str, data: Any) -> None:
        """Set this host's local clipboard from a decoded CLIPBOARD payload.

        Subclasses or tests may override; the default routes to the
        utils.clipboard helpers and accepts ``"text"`` / ``"image"`` kinds.
        """
        apply_clipboard(kind, data)

    # internals -----------------------------------------------------------

    def broadcast_chat(self, text: str, sender: str = "host") -> int:
        """Phase 5.2: send a chat message to every connected viewer.

        Returns the number of viewers the message was queued for, each on
        that viewer's own sender thread: a viewer that stopped reading, or
        whose bounded queue is full, does not hold the others.
        """
        if not isinstance(text, str) or not text:
            return 0
        payload = json.dumps(
            {"sender": sender, "text": text, "ts": time.time()},
        ).encode("utf-8")
        job = partial(_send_message, MessageType.CHAT, payload)
        return sum(client.push_outgoing("chat", job) for client in self._live_clients())

    def _build_channel(self, sock: socket.socket,
                       address: Tuple[Any, ...]) -> MessageChannel:
        """Hook for transports: TCP wraps directly, WS overrides this."""
        del address
        return TcpMessageChannel(sock)

    def _transport_name(self) -> str:
        """Identifier passed to approval callbacks. WS host overrides."""
        return "tcp"

    # context manager ----------------------------------------------------

    def __enter__(self) -> "RemoteDesktopHost":
        self.start()
        return self

    def __exit__(self, exc_type: Optional[type[BaseException]], exc: Optional[BaseException],
                 tb: Optional[TracebackType]) -> None:
        self.stop()
