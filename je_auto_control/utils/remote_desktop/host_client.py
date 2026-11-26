"""Per-connection handler for the TCP remote-desktop host.

One instance per connected viewer, owning that viewer's auth exchange,
sender thread, audio sender thread and receiver thread, plus the routing
table that turns an inbound message type into the right handler. The
owning :class:`~je_auto_control.utils.remote_desktop.host.RemoteDesktopHost`
is referenced only through the instance passed to ``__init__``, so this
module does not import it.
"""
import collections
import json
import queue
import threading
from typing import TYPE_CHECKING, Callable, Deque, List, NoReturn, Optional, Any, Set, Tuple

from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.exception.control_signals import raise_caused_run_interruption
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.remote_desktop.auth import make_nonce
from je_auto_control.utils.remote_desktop.clipboard_sync import (
    ClipboardEchoGuard, ClipboardSyncError, decode as decode_clipboard,
)
from je_auto_control.utils.remote_desktop.delta_frames import DeltaFrameGate
from je_auto_control.utils.remote_desktop.file_transfer import (
    FileTransferError, decode_begin,
)
from je_auto_control.utils.remote_desktop.host_access import (
    PERMISSION_DENIED, PERMISSION_FULL,
    PendingViewer, _AUTH_TIMEOUT_S, _interpret_approval,
)
from je_auto_control.utils.remote_desktop.input_dispatch import (
    InputDispatchError,
)
from je_auto_control.utils.remote_desktop.protocol import (
    AuthenticationError, MessageType, ProtocolError,
)
from je_auto_control.utils.remote_desktop.transport import MessageChannel

if TYPE_CHECKING:  # avoids a runtime cycle: host imports this module
    from je_auto_control.utils.remote_desktop.host import RemoteDesktopHost
    from je_auto_control.utils.remote_desktop.host_admission import PendingAdmission

_FILE_MSG_TYPES = frozenset({
    MessageType.FILE_BEGIN, MessageType.FILE_CHUNK, MessageType.FILE_END,
})


#: Messages a view-only viewer may not send, besides INPUT.
_CONTROL_MSG_TYPES = frozenset({MessageType.CLIPBOARD, *_FILE_MSG_TYPES})

#: A host-initiated send (chat, clipboard, file) run on the viewer's own thread.
OutgoingJob = Callable[[MessageChannel], None]


class _ClientHandler:
    """Per-connection auth + input-receive + frame-send state."""

    _AUDIO_QUEUE_MAXLEN = 50  # ~2.5 s of buffered chunks at 50 ms each
    _CURSOR_QUEUE_MAXLEN = 64  # ~2 s of updates at 30 Hz
    _OUTGOING_QUEUE_MAXSIZE = 64  # host-initiated sends waiting on one viewer

    def __init__(self, host: "RemoteDesktopHost",
                 channel: MessageChannel, address: Tuple[Any, ...],
                 admission: Optional["PendingAdmission"] = None) -> None:
        self._host = host
        #: The pending slot and auth deadline this connection holds until
        #: its credentials verify; ``None`` outside the host's accept path.
        self.admission = admission
        self._channel = channel
        self._address = address
        self._shutdown = threading.Event()
        self._sender_thread: Optional[threading.Thread] = None
        self._receiver_thread: Optional[threading.Thread] = None
        self._audio_queue: Deque[bytes] = collections.deque(
            maxlen=self._AUDIO_QUEUE_MAXLEN,
        )
        self._audio_lock = threading.Lock()
        self._audio_event = threading.Event()
        self._audio_sender_thread: Optional[threading.Thread] = None
        # Cursor updates waiting for the sender thread; guarded by _frame_cond.
        self._cursor_queue: Deque[bytes] = collections.deque(
            maxlen=self._CURSOR_QUEUE_MAXLEN,
        )
        # Chat, clipboard and file sends the host initiated, run on this
        # viewer's own rd-outgoing thread so a viewer that stopped reading
        # blocks only itself; full means the viewer is that far behind.
        self._outgoing: "queue.Queue[Tuple[str, OutgoingJob]]" = queue.Queue(
            maxsize=self._OUTGOING_QUEUE_MAXSIZE,
        )
        self._outgoing_lock = threading.Lock()
        self._outgoing_thread: Optional[threading.Thread] = None
        self.authenticated = False
        #: What this viewer and the host have exchanged over the clipboard,
        #: so a forwarded change is not sent back to where it came from.
        self.clipboard_guard = ClipboardEchoGuard()
        # Transfers this viewer began: aborted if it disconnects mid-file,
        # which used to leave the .part file and its open handle behind.
        self._transfer_ids: Set[str] = set()
        # Phase 5.3: per-client permission set by the approval callback.
        # Default is full control so legacy callers (no callback) keep
        # the prior behaviour.
        self.permission = PERMISSION_FULL

    @property
    def address(self) -> Tuple[Any, ...]:
        return self._address

    def start(self) -> None:
        """Run auth (with optional host approval), then start the loops.

        However the handshake fails, the handler is stopped: it was only
        closed, and the host reaps stopped handlers alone, so every failed
        login kept a ``max_clients`` slot until the host restarted. A
        watchdog bounds the whole handshake -- the socket timeout only bounds
        each read, and a peer trickling a byte at a time never tripped it.
        """
        watchdog = threading.Timer(_AUTH_TIMEOUT_S, self._close)
        watchdog.daemon = True
        watchdog.start()
        try:
            self._authenticate()
        except (AuthenticationError, ProtocolError, OSError) as error:
            autocontrol_logger.info(
                "remote_desktop client %s rejected: %r", self._address, error,
            )
            self.stop()
            return
        except Exception:  # noqa: BLE001  # reason: re-raised; the slot must be freed first
            self.stop()
            raise
        finally:
            watchdog.cancel()
        self.authenticated = True
        # The initial cursor + frame are seeded from _send_loop (the
        # per-client sender thread), not here: start() runs on this
        # connection's handshake thread with the socket timeout already
        # cleared, and a viewer that authenticates then stops reading would
        # pin that thread -- and its handshake slot -- until its buffer drains.
        self._sender_thread = threading.Thread(
            target=self._send_loop, name="rd-sender", daemon=True,
        )
        self._receiver_thread = threading.Thread(
            target=self._recv_loop, name="rd-recv", daemon=True,
        )
        self._sender_thread.start()
        self._receiver_thread.start()
        if self._host._audio_config.enabled:
            self._audio_sender_thread = threading.Thread(
                target=self._audio_send_loop, name="rd-audio", daemon=True,
            )
            self._audio_sender_thread.start()

    def _send_initial_frame(self) -> None:
        """Forward the most recent encoded frame so new clients aren't blank.

        Motion-dedup in :meth:`_capture_loop` means a static desktop
        only bumps ``_latest_seq`` once; replaying that frame to the
        new client keeps them from sitting on a black popup until the
        host moves something.
        """
        with self._host._frame_cond:
            frame = self._host._latest_frame
        if frame is None:
            return
        try:
            self._channel.send_typed(MessageType.FRAME, frame)
        except (OSError, ProtocolError):
            pass

    def push_audio(self, chunk: bytes) -> None:
        """Enqueue a PCM chunk for delivery; oldest dropped if queue is full."""
        if self._shutdown.is_set() or not self.authenticated:
            return
        with self._audio_lock:
            self._audio_queue.append(chunk)
        self._audio_event.set()

    def push_cursor(self, payload: bytes) -> None:
        """Enqueue a CURSOR payload for the sender thread; oldest dropped if full."""
        with self._host._frame_cond:
            self._cursor_queue.append(payload)
            self._host._frame_cond.notify_all()

    def push_outgoing(self, what: str, job: OutgoingJob) -> bool:
        """Queue a host-initiated send for this viewer's own sender thread.

        ``False`` when the viewer is gone or so far behind that its bounded
        queue is full: the send is dropped for this viewer only.
        """
        if self._shutdown.is_set():
            return False
        try:
            self._outgoing.put_nowait((what, job))
        except queue.Full:
            autocontrol_logger.warning(
                "remote_desktop %s to %s dropped: the viewer is not reading", what, self._address,
            )
            return False
        with self._outgoing_lock:
            if self._outgoing_thread is None:
                self._outgoing_thread = threading.Thread(
                    target=self._outgoing_loop, name="rd-outgoing", daemon=True,
                )
                self._outgoing_thread.start()
        return True

    def _outgoing_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                what, job = self._outgoing.get(timeout=0.5)
            except queue.Empty:
                continue
            if self._shutdown.is_set():
                return
            try:
                job(self._channel)
            except OSError as error:
                autocontrol_logger.info(
                    "remote_desktop %s send to %s failed: %r", what, self._address, error,
                )
                self.stop()
                return
            except ProtocolError as error:
                autocontrol_logger.warning(
                    "remote_desktop %s to %s not sent: %r", what, self._address, error,
                )

    def stop(self) -> None:
        """Signal threads, abandon this viewer's unfinished uploads, close the socket."""
        self._shutdown.set()
        receiver = self._host._file_receiver
        if receiver is not None:
            # reason (suppression below): the receive thread adds ids meanwhile, so this walks a snapshot
            for transfer_id in list(self._transfer_ids):  # NOSONAR python:S7504
                receiver.abort(transfer_id, "viewer disconnected")
        with self._host._frame_cond:
            self._host._frame_cond.notify_all()
        self._audio_event.set()
        self._close()

    def _resolve_permission(self) -> str:
        """Run the host's optional approval callback after token auth.

        Returns one of :data:`PERMISSION_FULL` / :data:`PERMISSION_VIEW_ONLY`
        (admit) or :data:`PERMISSION_DENIED` (reject). The caller is
        expected to send ``AUTH_FAIL`` and raise on denial — keeping
        that wire-level handling inside :meth:`_authenticate` so the
        viewer sees the rejection before it has a chance to flip into
        the post-handshake state where ``AUTH_FAIL`` is ignored.
        """
        callback = self._host._on_pending_viewer
        if callback is None:
            return PERMISSION_FULL
        pending = PendingViewer(
            address=tuple(self._address) if self._address else (),
            host_id=self._host.host_id,
            transport=self._host._transport_name(),
        )
        try:
            return _interpret_approval(callback(pending))
        except Exception as error:  # noqa: BLE001  # reason: user callback; any failure denies the viewer
            autocontrol_logger.info(
                "remote_desktop approval callback raised for %s: %r",
                self._address, error,
            )
            return PERMISSION_DENIED

    def _pending_read_timeout(self) -> float:
        """Socket timeout while unauthenticated: the pending deadline's time left, if any."""
        if self.admission is None:
            return _AUTH_TIMEOUT_S
        return self.admission.read_timeout()

    def _authenticate(self) -> None:
        nonce = make_nonce()
        self._channel.settimeout(self._pending_read_timeout())
        self._channel.send_typed(MessageType.AUTH_CHALLENGE, nonce)
        msg_type, payload = self._channel.read_typed()
        if msg_type is not MessageType.AUTH_RESPONSE:
            self._reject_auth(b"expected AUTH_RESPONSE", f"expected AUTH_RESPONSE, got {msg_type.name}")
        # Phase 6.6: a viewer reconnecting with a valid resume token
        # signs with that token directly — host short-circuits the
        # approval popup and reuses the saved permission.
        resumed = self._host._try_consume_resume(nonce, payload)
        if resumed is None and not self._host._verify_token(nonce, payload):
            self._reject_auth(b"bad token", "bad token")
        # Only now, credentials proven, does the connection take a viewer
        # slot: an unauthenticated one used to hold it for up to 60 s.
        self._channel.settimeout(_AUTH_TIMEOUT_S)
        if not self._host._admit_client(self):
            self._reject_auth(b"host full", "no viewer slot")
        if resumed is not None:
            self.permission = resumed
        else:
            # Host operator gates the session *before* AUTH_OK so the
            # viewer surfaces the rejection as an AuthenticationError
            # instead of connecting and then mysteriously disconnecting.
            permission = self._resolve_permission()
            if permission == PERMISSION_DENIED:
                self._reject_auth(b"rejected by host", "rejected by host")
            self.permission = permission
        # Issue a fresh resume token so the viewer can reconnect
        # within the store's TTL without the approval popup.
        resume_token = self._host._resume_store.issue(self.permission)
        ok_payload = json.dumps(
            {"host_id": self._host.host_id,
             "resume_token": resume_token,
             "resume_ttl": self._host._resume_store.ttl,
             "codec": self._host._codec_provider.name},
            ensure_ascii=False,
        ).encode("utf-8")
        self._channel.send_typed(MessageType.AUTH_OK, ok_payload)
        self._channel.settimeout(None)

    def _reject_auth(self, payload: bytes, message: str) -> NoReturn:
        """Release admission capacity before the terminal reply lets the viewer immediately reconnect."""
        self._shutdown.set()
        if self.admission is not None:
            self.admission.settle()
        self._channel.send_typed(MessageType.AUTH_FAIL, payload)
        raise AuthenticationError(message)

    def _send_loop(self) -> None:
        # Seed the viewer with the latest cursor + frame on this per-client
        # sender thread (Phase 2.3: motion-aware capture only bumps the seq on
        # change, so a viewer joining a static desktop would otherwise sit
        # blank until the host moves). Doing it here rather than in start()
        # keeps a slow-reading viewer from stalling the accept thread.
        self._host._send_initial_cursor(self)
        # JPEG frames stand alone and only the newest is sent; a delta-coded
        # stream goes through a gate that keeps it decodable (delta_frames).
        gate = None if self._host._delta_history is None else DeltaFrameGate()
        if gate is None:
            self._send_initial_frame()
        last_sent = 0
        while True:
            outgoing, delta_frames, last_sent = self._next_streamed(last_sent, gate)
            if self._shutdown.is_set():
                return
            for msg_type, payload in outgoing:
                if not self._send_streamed(msg_type, payload):
                    return
            if gate is not None and not self._send_delta_frames(delta_frames, gate):
                return

    def _next_streamed(self, last_sent: int, gate: Optional[DeltaFrameGate],
                       ) -> Tuple[List[Tuple[MessageType, bytes]], List[bytes], int]:
        """Wait for cursor updates or a frame newer than ``last_sent``.

        Returns the cursor updates (plus, for JPEG, the newest frame), the
        delta-coded frames the gate lets through, and the new mark.
        """
        host = self._host
        with host._frame_cond:
            while (not self._shutdown.is_set() and not self._cursor_queue
                   and host._latest_seq <= last_sent):
                host._frame_cond.wait(timeout=0.5)
            outgoing = [(MessageType.CURSOR, cursor) for cursor in self._cursor_queue]
            self._cursor_queue.clear()
            frame = host._latest_frame
            seq = host._latest_seq
            history = host._delta_history
            delta_frames = [] if gate is None or history is None else gate.take(history)
        if gate is None and frame is not None and seq > last_sent:
            outgoing.append((MessageType.FRAME, frame))
        return outgoing, delta_frames, seq

    def _send_delta_frames(self, frames: List[bytes], gate: DeltaFrameGate) -> bool:
        """Send delta-coded frames in order; ``False`` once the connection is gone.

        A frame that cannot be sent takes the rest of the batch with it --
        they reference it -- and, like a viewer that fell behind, leaves the
        gate waiting for a keyframe, which is then asked for.
        """
        for payload in frames:
            sent = self._try_send(MessageType.FRAME, payload)
            if sent is None:
                return False
            if not sent:
                gate.lose()
                break
        if gate.needs_keyframe:
            self._host._request_keyframe()
        return True

    def _send_streamed(self, msg_type: MessageType, payload: bytes) -> bool:
        """Send one streamed message; ``False`` once the connection is gone."""
        return self._try_send(msg_type, payload) is not None

    def _try_send(self, msg_type: MessageType, payload: bytes) -> Optional[bool]:
        """Send one streamed message: ``True`` sent, ``False`` skipped, ``None`` connection gone."""
        try:
            self._channel.send_typed(msg_type, payload)
        except OSError as error:
            autocontrol_logger.info(
                "remote_desktop send to %s failed: %r",
                self._address, error,
            )
            self.stop()
            return None
        except ProtocolError as error:
            # Over the payload cap: that one message is skipped. Raising ended
            # this thread while the viewer stayed connected and in control.
            autocontrol_logger.warning(
                "remote_desktop %s to %s not sent: %r",
                msg_type.name, self._address, error,
            )
            return False
        return True

    def _audio_send_loop(self) -> None:
        while not self._shutdown.is_set():
            self._audio_event.wait(timeout=0.5)
            if self._shutdown.is_set():
                return
            while True:
                with self._audio_lock:
                    if not self._audio_queue:
                        self._audio_event.clear()
                        break
                    chunk = self._audio_queue.popleft()
                try:
                    self._channel.send_typed(MessageType.AUDIO, chunk)
                except OSError as error:
                    autocontrol_logger.info(
                        "remote_desktop audio send to %s failed: %r",
                        self._address, error,
                    )
                    self.stop()
                    return

    def _recv_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                msg_type, payload = self._channel.read_typed()
            except (OSError, ProtocolError) as error:
                if not self._shutdown.is_set():
                    autocontrol_logger.info(
                        "remote_desktop recv from %s ended: %r",
                        self._address, error,
                    )
                self.stop()
                return
            if self._shutdown.is_set() or not self.authenticated:
                self.stop()
                return
            try:
                self._route_incoming(msg_type, payload)
            except BaseException:
                # Dying here without stop() left a handler that still
                # counted as an authenticated client: it ignored all later
                # input and held a slot that locked out new viewers.
                self.stop()
                raise

    def _route_incoming(self, msg_type: MessageType, payload: bytes) -> None:
        """Dispatch one received message to the matching handler."""
        if msg_type is MessageType.PING:
            return
        if msg_type is MessageType.INPUT:
            # Phase 5.3: drop input from view-only viewers so they can
            # watch but cannot drive the mouse / keyboard.
            if self.permission == PERMISSION_FULL:
                self._handle_input_payload(payload)
            return
        if msg_type in _CONTROL_MSG_TYPES and self.permission != PERMISSION_FULL:
            # Setting the host clipboard or writing files on it is control,
            # not viewing: a file dropped in the Startup folder is full
            # control at the next logon.
            autocontrol_logger.info(
                "remote_desktop unprivileged viewer %s sent %s; dropped",
                self._address, msg_type.name,
            )
            return
        if msg_type is MessageType.CLIPBOARD:
            self._handle_clipboard_payload(payload)
            return
        if msg_type is MessageType.CHAT:
            self._handle_chat_payload(payload)
            return
        if msg_type is MessageType.USB_LIST_REQUEST:
            self._handle_usb_list_request()
            return
        if msg_type in _FILE_MSG_TYPES:
            self._handle_file_payload(msg_type, payload)
            return
        autocontrol_logger.info(
            "remote_desktop unexpected msg %s from %s",
            msg_type.name, self._address,
        )

    def _handle_file_payload(self, msg_type: MessageType,
                             payload: bytes) -> None:
        receiver = self._host._ensure_file_receiver()
        try:
            if msg_type is MessageType.FILE_BEGIN:
                self._transfer_ids.add(decode_begin(payload)[0])
                receiver.handle_begin(payload)
            elif msg_type is MessageType.FILE_CHUNK:
                receiver.handle_chunk(payload)
            elif msg_type is MessageType.FILE_END:
                receiver.handle_end(payload)
        except FileTransferError as error:
            autocontrol_logger.info(
                "remote_desktop bad file message from %s: %r",
                self._address, error,
            )

    def _handle_usb_list_request(self) -> None:
        """Phase 6.9: enumerate the host's USB devices and ship the list back.

        Uses the existing :func:`list_usb_devices` helper so we get the
        same cross-platform behaviour as the standalone USB module.
        Errors fall back to an empty payload — the viewer should
        treat that as "host has no usable USB backend" rather than
        crashing.
        """
        try:
            from je_auto_control.utils.usb import list_usb_devices
            result = list_usb_devices()
            body = {
                "backend": result.backend,
                "devices": [d.to_dict() for d in result.devices],
            }
        except (ImportError, OSError, RuntimeError) as error:
            autocontrol_logger.info(
                "usb_list from %s failed: %r", self._address, error,
            )
            body = {"backend": "unavailable", "devices": []}
        try:
            self._channel.send_typed(
                MessageType.USB_LIST_RESPONSE,
                json.dumps(body, ensure_ascii=False).encode("utf-8"),
            )
        except OSError:
            pass

    def _handle_chat_payload(self, payload: bytes) -> None:
        """Forward viewer-originated chat to the host's optional callback."""
        callback = self._host._on_chat
        if callback is None:
            return
        try:
            body = json.loads(payload.decode("utf-8"))
        except (ValueError, RecursionError):   # also the int-digit and nesting limits
            return
        if not isinstance(body, dict):
            return
        text = body.get("text")
        sender = body.get("sender", "viewer")
        if not isinstance(text, str) or not text:
            return
        try:
            callback(str(sender), text)
        except Exception:  # noqa: BLE001  # reason: callback isolation, a caller's handler must not kill the receive loop
            autocontrol_logger.exception(
                "remote_desktop on_chat callback raised"
            )

    def _handle_clipboard_payload(self, payload: bytes) -> None:
        try:
            kind, data = decode_clipboard(payload)
        except ClipboardSyncError as error:
            raise_caused_run_interruption(error)
            autocontrol_logger.info(
                "remote_desktop bad CLIPBOARD from %s: %r",
                self._address, error,
            )
            return
        if self._shutdown.is_set() or not self.authenticated or self.permission != PERMISSION_FULL:
            return
        # Noted before it is applied: a watcher that sees the clipboard
        # change the moment it is set must already find the note.
        self.clipboard_guard.note_remote(kind, data)
        try:
            self._host._apply_clipboard(kind, data)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise_caused_run_interruption(error)
            autocontrol_logger.warning(
                "remote_desktop clipboard apply failed for %s: %r",
                self._address, error,
            )

    def _handle_input_payload(self, payload: bytes) -> None:
        try:
            message = json.loads(payload.decode("utf-8"))
        except (ValueError, RecursionError) as error:
            autocontrol_logger.info(
                "remote_desktop bad INPUT from %s: %r",
                self._address, error,
            )
            return
        try:
            self._host._dispatch(message)
        except InputDispatchError as error:
            autocontrol_logger.info(
                "remote_desktop rejected INPUT from %s: %r",
                self._address, error,
            )
        # AutoControlException: the wrappers raise it for an unknown key or
        # button name, which is the peer's input, not the host failing.
        except (OSError, RuntimeError, ValueError, TypeError,
                AutoControlException) as error:
            autocontrol_logger.warning(
                "remote_desktop input apply failed for %s: %r",
                self._address, error,
            )

    def _close(self) -> None:
        self._channel.close()
