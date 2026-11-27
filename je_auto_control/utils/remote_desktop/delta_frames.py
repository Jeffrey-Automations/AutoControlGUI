"""Keyframe-aware frame delivery for delta-coded (H.264 / HEVC) TCP streams.

JPEG frames stand alone, so the TCP host sends a slow viewer only the
newest one. An H.264 P-frame only decodes on top of the frames before it:
sent the newest packet and nothing in between, a viewer's decoder showed
corrupted video until the next keyframe, up to a whole GOP later. Here a
delta-coded stream keeps a short shared backlog instead; a viewer that
falls further behind than that is sent nothing more until a keyframe, and
asks the encoder (rate-limited) for one so it does not wait out the GOP.
"""
import collections
import threading
import time
from dataclasses import dataclass
from typing import Callable, Deque, List, Optional

from je_auto_control.utils.remote_desktop.video_codec import CODEC_JPEG

#: Packets of a delta-coded stream kept for viewers that are behind; one
#: further behind than this has dropped a frame and resynchronises.
DELTA_BACKLOG_FRAMES = 8
#: Shortest gap between two keyframes forced for resynchronising viewers.
KEYFRAME_REQUEST_INTERVAL_S = 1.0


@dataclass(frozen=True)
class EncodedFrame:
    """One wire-ready packet of a delta-coded stream and its place in it."""

    seq: int
    payload: bytes
    keyframe: bool


class DeltaFrameHistory:
    """The newest packets of a delta-coded stream, shared by every viewer and bounded.

    Not locked itself: the host mutates and reads it under its frame
    condition, the same lock that guards the newest frame and its sequence.
    """

    def __init__(self, maxlen: int = DELTA_BACKLOG_FRAMES) -> None:
        if int(maxlen) < 1:
            raise ValueError("maxlen must be at least 1")
        self._frames: Deque[EncodedFrame] = collections.deque(maxlen=int(maxlen))

    def append(self, frame: EncodedFrame) -> None:
        """Add the newest packet; the oldest falls out once the backlog is full."""
        self._frames.append(frame)

    def after(self, seq: int) -> List[EncodedFrame]:
        """Packets newer than ``seq``, oldest first."""
        return [frame for frame in self._frames if frame.seq > seq]


def history_for_codec(codec: str) -> Optional[DeltaFrameHistory]:
    """A fresh backlog for a delta codec; ``None`` for JPEG, whose frames stand alone."""
    return None if codec == CODEC_JPEG else DeltaFrameHistory()


class DeltaFrameGate:
    """One viewer's place in a delta-coded stream.

    It hands out packets strictly in order and never one whose reference
    the viewer missed: after a gap -- the backlog moved past what the viewer
    was sent, or a packet could not be sent -- nothing is handed out until
    the next keyframe. A new viewer starts that way, at the newest keyframe
    still in the backlog.
    """

    def __init__(self) -> None:
        self._last_seq = 0
        self._synced = False
        self.resyncs = 0

    @property
    def last_seq(self) -> int:
        """The newest sequence number this viewer has been handed or skipped."""
        return self._last_seq

    @property
    def needs_keyframe(self) -> bool:
        """``True`` while this viewer can only resume at a keyframe."""
        return not self._synced

    def take(self, history: DeltaFrameHistory) -> List[bytes]:
        """Return the packets to send now, in order; may be empty."""
        pending = history.after(self._last_seq)
        if not pending:
            return []
        if self._synced and pending[0].seq != self._last_seq + 1:
            self.lose()
        self._last_seq = pending[-1].seq
        if not self._synced:
            start = next((index for index, frame in enumerate(pending) if frame.keyframe), None)
            if start is None:
                return []
            self._synced = True
            pending = pending[start:]
        return [frame.payload for frame in pending]

    def lose(self) -> None:
        """A packet handed out was not delivered: drop everything until a keyframe."""
        if self._synced:
            self.resyncs += 1
        self._synced = False


class KeyframeRequests:
    """Keyframe requests from viewer sender threads to the capture loop, rate-limited.

    Host-wide: however many viewers resynchronise, at most one keyframe is
    forced per ``min_interval_s``; a viewer still waiting asks again later.
    """

    def __init__(self, min_interval_s: float = KEYFRAME_REQUEST_INTERVAL_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._min_interval_s = float(min_interval_s)
        self._clock = clock
        self._lock = threading.Lock()
        self._pending = False
        self._last_request: Optional[float] = None

    def request(self) -> bool:
        """Ask for a keyframe; ``False`` when one is already pending or was asked for too recently."""
        with self._lock:
            now = self._clock()
            recent = (self._last_request is not None
                      and now - self._last_request < self._min_interval_s)
            if self._pending or recent:
                return False
            self._pending = True
            self._last_request = now
            return True

    def take(self) -> bool:
        """Consume the pending request, if any (the capture loop's side)."""
        with self._lock:
            pending, self._pending = self._pending, False
            return pending


__all__ = [
    "DELTA_BACKLOG_FRAMES", "KEYFRAME_REQUEST_INTERVAL_S",
    "DeltaFrameGate", "DeltaFrameHistory", "EncodedFrame", "KeyframeRequests", "history_for_codec",
]
