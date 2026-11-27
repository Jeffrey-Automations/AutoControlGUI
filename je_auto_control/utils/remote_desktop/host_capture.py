"""Frame and cursor production for the TCP remote-desktop host.

What the host streams, as opposed to how it streams it: monitor
enumeration, mapping a monitor index to a capture region, and the default
providers that turn a screen grab into JPEG bytes and read the cursor
position. Every one of them degrades to a working fallback when the
optional dependency (``mss``, Pillow) is missing, so a stock install
still hosts.
"""
import json
import threading
import time
from io import BytesIO
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple,
)

from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.remote_desktop.delta_frames import (
    DeltaFrameHistory, EncodedFrame, KeyframeRequests,
)
from je_auto_control.utils.remote_desktop.protocol import MessageType
from je_auto_control.utils.remote_desktop.video_codec import (
    CODEC_JPEG, CodecProvider, codec_tag, is_keyframe_packet,
)

if TYPE_CHECKING:  # avoids a runtime cycle: host_client is a sibling
    from je_auto_control.utils.remote_desktop.host_client import (
        _ClientHandler,
    )


FrameProvider = Callable[[], bytes]

CursorProvider = Callable[[], Optional[Sequence[int]]]
"""Return ``(x, y)`` in host screen coordinates, or ``None`` to skip a tick."""

_DEFAULT_QUALITY = 70

_CURSOR_POLL_INTERVAL_S = 1.0 / 30.0  # 30 Hz: smooth, low CPU on idle.

def list_host_monitors() -> List[Dict[str, Any]]:
    """Headless helper: return every monitor's geometry.

    Index 0 spans all monitors (the ``mss`` convention). Returns an
    empty list if ``mss`` is not installed, so GUI callers can show a
    disabled control instead of crashing.
    """
    from je_auto_control.utils.cv2_utils.screen_grabber import mss_grabber
    try:
        grabber = mss_grabber()
    except ImportError:
        return []
    with grabber as sct:
        return [
            {
                "index": index, "left": int(monitor["left"]),
                "top": int(monitor["top"]),
                "width": int(monitor["width"]),
                "height": int(monitor["height"]),
                "is_combined": index == 0,
            }
            for index, monitor in enumerate(sct.monitors)
        ]

def _resolve_monitor_region(
        monitor_index: int) -> Optional[Sequence[int]]:
    """Map an ``mss`` monitor index to ``(x, y, width, height)``.

    Returns ``None`` (full-screen capture fallback) when ``mss`` is
    not available so a stock install still works.
    """
    from je_auto_control.utils.cv2_utils.screen_grabber import mss_grabber
    try:
        grabber = mss_grabber()
    except ImportError:
        autocontrol_logger.warning(
            "remote_desktop monitor_index=%d ignored: mss not installed",
            monitor_index,
        )
        return None
    with grabber as sct:
        if monitor_index < 0 or monitor_index >= len(sct.monitors):
            raise ValueError(
                f"monitor_index {monitor_index} out of range "
                f"(0..{len(sct.monitors) - 1})"
            )
        mon = sct.monitors[monitor_index]
        return (
            int(mon["left"]), int(mon["top"]),
            int(mon["width"]), int(mon["height"]),
        )

def capture_origin(region: Optional[Sequence[int]]) -> Tuple[int, int]:
    """Screen position of the default frame provider's top-left pixel.

    The region's corner, or for a full capture the virtual desktop's, which
    is negative when a monitor sits above or left of the primary one.
    ``(0, 0)`` when ``mss`` is unavailable to say.
    """
    if region is not None:
        return int(region[0]), int(region[1])
    try:
        monitors = list_host_monitors()
    except Exception as error:  # noqa: BLE001  # reason: mss raises its own ScreenShotError (no display, no permission); the host still starts, as it did before the origin was read
        autocontrol_logger.warning("remote_desktop: monitor layout unavailable, input unshifted: %r", error)
        return 0, 0
    if not monitors:
        return 0, 0
    return monitors[0]["left"], monitors[0]["top"]


def _resolve_cursor_provider(
        explicit: Optional[CursorProvider],
        enabled: bool, origin: Tuple[int, int] = (0, 0)) -> Optional[CursorProvider]:
    """Pick the cursor provider — explicit > default > disabled.

    The default one reports the pointer relative to ``origin``, the frame's
    top-left: the viewer draws it in frame coordinates.
    """
    if explicit is not None:
        return explicit
    return _default_cursor_provider(origin) if enabled else None

def _default_cursor_provider(origin: Tuple[int, int] = (0, 0)) -> CursorProvider:
    """Build a cursor-position poller using the project's mouse wrapper.

    The wrapper is imported lazily inside the closure so importing this
    module on platforms where mouse capture is unavailable does not
    blow up. Returns ``None`` on read failures so the broadcast loop
    silently skips the tick instead of crashing the host.
    """
    def provide() -> Optional[Sequence[int]]:
        try:
            from je_auto_control.wrapper.auto_control_mouse import (
                get_mouse_position,
            )
        except ImportError:
            return None
        try:
            position = get_mouse_position()
        except (OSError, RuntimeError, AttributeError, AutoControlException):
            return None
        if position is None:
            return None
        return int(position[0]) - origin[0], int(position[1]) - origin[1]
    return provide

def _default_frame_provider(region: Optional[Sequence[int]] = None,
                            quality: int = _DEFAULT_QUALITY) -> FrameProvider:
    """Build a JPEG frame producer using the platform's screen grabber."""
    def provide() -> bytes:
        # local import: not needed for unit tests
        from je_auto_control.utils.cv2_utils.screen_grabber import image_grabber
        grabber = image_grabber()
        if region is not None:
            x, y, width, height = (int(v) for v in region)
            bbox = (x, y, x + width, y + height)
            image = grabber.grab(bbox=bbox, all_screens=True)
        else:
            image = grabber.grab(all_screens=True)
        if image.mode != "RGB":
            image = image.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=int(quality))
        return buffer.getvalue()
    return provide


class FrameProductionMixin:
    """Frame and cursor production half of :class:`RemoteDesktopHost`.

    The loops that turn the host screen into what viewers receive: the
    ~30 Hz cursor poll, the capture loop that paces frames at the
    configured fps, and the codec step between a JPEG frame and the bytes
    that go on the wire. Each loop is handed its run's stop event rather
    than reading the host's, so a restart cannot revive it. Requires the
    host to provide ``_clients``/``_clients_lock``, ``_frame_provider``,
    ``_cursor_provider``, ``_codec``, ``_fps``, ``_latest_frame``,
    ``_frame_lock``, and for delta codecs ``_delta_history`` (the backlog
    viewers are fed from in order) and ``_keyframe_requests``.
    """

    if TYPE_CHECKING:
        # Declared, never defined: the host class this is mixed into owns
        # every one of these. The block is stripped at runtime, so nothing
        # here can shadow what the host actually binds.
        _clients: List["_ClientHandler"]
        _clients_lock: threading.Lock
        _frame_cond: threading.Condition
        _frame_provider: FrameProvider
        _cursor_provider: Optional[CursorProvider]
        _cursor_lock: threading.Lock
        _latest_cursor_payload: Optional[bytes]
        _latest_frame: Optional[bytes]
        _codec_provider: CodecProvider
        _latest_seq: int
        _period: float
        _delta_history: Optional[DeltaFrameHistory]
        _keyframe_requests: KeyframeRequests

    def _cursor_loop(self, stop: threading.Event) -> None:
        """Poll cursor position at ~30 Hz and push it to viewers as JSON."""
        provider = self._cursor_provider
        if provider is None:
            return
        while not stop.is_set():
            position = provider()
            if position is not None and len(position) >= 2:
                payload = json.dumps(
                    {"x": int(position[0]), "y": int(position[1]),
                     "visible": True},
                ).encode("utf-8")
                with self._cursor_lock:
                    is_new = payload != self._latest_cursor_payload
                    self._latest_cursor_payload = payload
                if is_new:
                    self._broadcast_cursor(payload)
            if stop.wait(timeout=_CURSOR_POLL_INTERVAL_S):
                return

    def _broadcast_cursor(self, payload: bytes) -> None:
        """Hand a CURSOR message to every authenticated client's sender thread.

        Never written here: this runs on the one cursor thread, and a viewer
        that stopped reading held it inside its full socket buffer, freezing
        the cursor of every other viewer.
        """
        with self._clients_lock:
            clients = [c for c in self._clients
                       if c.authenticated and not c._shutdown.is_set()]
        for client in clients:
            client.push_cursor(payload)

    def broadcast_viewer_cursor(self, viewer_id: str,
                                x: int, y: int) -> int:
        """Phase 5.1: relay one viewer's cursor position to every other viewer.

        Typically called by :class:`MultiViewerHost` when several
        viewers share a session so each viewer's overlay can show the
        other operators' pointers (Figma / Google Docs style). The
        viewer_id is opaque to the host — viewers use it to colour-key
        their overlay.
        """
        payload = json.dumps(
            {"x": int(x), "y": int(y), "visible": True,
             "viewer_id": str(viewer_id)},
        ).encode("utf-8")
        with self._clients_lock:
            clients = [c for c in self._clients
                       if c.authenticated and not c._shutdown.is_set()]
        for client in clients:
            client.push_cursor(payload)
        return len(clients)

    def _send_initial_cursor(self, client: "_ClientHandler") -> None:
        """Push the latest known cursor position to a fresh client.

        Sending unconditionally on auth means the viewer sees a cursor
        immediately instead of waiting up to ~1 s for the next position
        change. Safe to call when the cursor loop is disabled — we
        only send if there's a payload to send.
        """
        with self._cursor_lock:
            payload = self._latest_cursor_payload
        if payload is None:
            return
        try:
            client._channel.send_typed(MessageType.CURSOR, payload)
        except OSError:
            pass

    def _capture_loop(self, stop: threading.Event) -> None:
        next_tick = time.monotonic()
        last_frame_hash: Optional[int] = None
        while not stop.is_set():
            try:
                frame = self._frame_provider()
            except (OSError, RuntimeError, ValueError, AutoControlException) as error:
                autocontrol_logger.warning(
                    "remote_desktop frame capture failed: %r", error,
                )
                stop.wait(self._period)
                continue
            # Phase 2.3: drop frames that are byte-identical to the
            # previous capture. A static desktop produces the same JPEG
            # every tick (JPEG is deterministic for identical input),
            # so this skip costs nothing extra on motion-heavy
            # workloads and saves a full FPS-worth of TCP / encoder
            # bandwidth at idle.
            frame_hash = hash(frame)
            # A keyframe a resynchronising viewer asked for is encoded even
            # from an unchanged screen: nothing else would ever produce it.
            forced = self._keyframe_requests.take() and self._ask_encoder_for_keyframe()
            if frame_hash != last_frame_hash or forced:
                self._publish_frame(frame)
                last_frame_hash = frame_hash
            next_tick += self._period
            sleep_for = max(0.0, next_tick - time.monotonic())
            if sleep_for <= 0.0:
                next_tick = time.monotonic()
            stop.wait(sleep_for)

    def _publish_frame(self, frame: bytes) -> None:
        """Encode one captured JPEG and make each packet the newest frame.

        Phase 6.8: JpegPassthrough yields the bytes unchanged so the wire
        format stays identical for stock clients. A delta codec's packets
        also go into the backlog its viewers are fed from in order.
        """
        for encoded, keyframe in self._encode_for_wire(frame):
            with self._frame_cond:
                self._latest_frame = encoded
                self._latest_seq += 1
                if self._delta_history is not None:
                    self._delta_history.append(EncodedFrame(self._latest_seq, encoded, keyframe))
                self._frame_cond.notify_all()

    def _request_keyframe(self) -> None:
        """A viewer of a delta-coded stream has to resynchronise: ask for a keyframe.

        Rate-limited host-wide by :class:`KeyframeRequests`; a JPEG stream
        has nothing to resynchronise, so there it does nothing.
        """
        if self._delta_history is not None:
            self._keyframe_requests.request()

    def _ask_encoder_for_keyframe(self) -> bool:
        """Have the codec make its next packet a keyframe; ``False`` when it cannot."""
        request = getattr(self._codec_provider, "request_keyframe", None)
        if request is None:
            return False
        try:
            return bool(request())
        except Exception as error:  # noqa: BLE001  # reason: the provider is pluggable (PyAV errors derive from Exception alone); the viewer then waits for a natural keyframe
            autocontrol_logger.warning("remote_desktop keyframe request failed: %r", error)
            return False

    def _encode_for_wire(self, jpeg_bytes: bytes) -> Iterator[Tuple[bytes, bool]]:
        """Wrap codec output with a 1-byte tag (skipped for JPEG); each with whether it is a keyframe."""
        provider = self._codec_provider
        if provider.name == CODEC_JPEG:
            yield jpeg_bytes, True  # legacy wire format: no tag, raw JPEG
            return
        tag = bytes([codec_tag(provider.name)])
        try:
            packets = provider.encode_jpeg(jpeg_bytes)
        except Exception as error:  # noqa: BLE001  # reason: the provider is pluggable, and PyAV's errors derive from Exception alone; one frame is lost, not the capture loop
            autocontrol_logger.warning(
                "remote_desktop codec %s failed: %r", provider.name, error,
            )
            return
        check = getattr(provider, "is_keyframe", None)
        for packet in packets:
            body = bytes(packet)
            keyframe = check(body) if check is not None else is_keyframe_packet(provider.name, body)
            yield tag + body, bool(keyframe)
