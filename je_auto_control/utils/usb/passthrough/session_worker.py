"""Per-session worker that keeps blocking USB work off the WebRTC event loop.

The ``usb`` DataChannel's message handler runs on the event loop that every
WebRTC session shares, and one USB transfer may sit in the backend for up to
``MAX_TIMEOUT_MS`` (60 s); an ACL prompt waits on the operator. Serving
frames there froze every session's video, input and other channels, so the
handler only calls :meth:`UsbSessionWorker.submit` and the worker runs
:meth:`UsbPassthroughSession.handle_frame` on its own threads.

Ordering and concurrency:

* each live claim has a *lane* -- a FIFO served by one thread at a time --
  so one claim's transfers, CREDIT and CLOSE frames keep their order while
  other claims run in parallel;
* OPEN, LIST, RESUME and frames that name no live claim share the session
  lane, so a slow open or prompt never holds up a claim's transfers;
* each session (one per viewer channel) has its own worker, so sessions
  never wait for each other.

A lane's thread lingers ``idle_s`` for more work and then exits, and exits
at once when its claim is gone, so threads stay bounded by the live claims.

The queue is bounded per session (``max_pending`` frames waiting, not yet
being served): beyond it a frame is refused, and the caller answers it with
the protocol's ERROR frame. :meth:`UsbSessionWorker.close` drops what is
queued, releases every claim (``close_all``, which never waits on the device)
and joins its threads for at most ``join_timeout_s``; a thread still inside
the backend after that finishes on its own (the backend bounds a transfer at
``MAX_TIMEOUT_MS``), its result is discarded, and the session closes its
handle.

Such *abandoned* threads are never killed, but they are counted across the
process: while ``max_abandoned`` of them (from any closed session) are still
inside the backend, a new claim (OPEN or RESUME) is refused with
``ABANDONED_MESSAGE``, which the viewer receives as a ``UsbClientError``. A
viewer that keeps reconnecting while its transfers hang can therefore not pile
up more than that many threads on the host; claims it already holds keep
working, and new ones are accepted again as the abandoned threads finish.

Replies are handed to ``send_reply`` from the worker threads; the channel
host passes one that marshals the send onto the event loop
(``call_soon_threadsafe`` through the WebRTC bridge).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, List, Optional, Set

from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.usb.passthrough.protocol import Frame, Opcode
from je_auto_control.utils.usb.passthrough.session import UsbPassthroughSession

#: Opcodes that belong to one claim and keep their order behind its transfers.
_CLAIM_OPCODES = frozenset({
    Opcode.CTRL, Opcode.BULK, Opcode.INT, Opcode.CREDIT, Opcode.CLOSE,
})
#: Opcodes that ask for a new claim, refused while too many abandoned threads remain.
_NEW_CLAIM_OPCODES = frozenset({Opcode.OPEN, Opcode.RESUME})
_SESSION_LANE = -1
DEFAULT_MAX_ABANDONED = 16
DEFAULT_IDLE_S = 2.0
DEFAULT_JOIN_TIMEOUT_S = 0.1
QUEUE_FULL_MESSAGE = "usb request queue full"
CLOSED_MESSAGE = "usb channel closed"
NO_WORKER_MESSAGE = "usb worker unavailable"
ABANDONED_MESSAGE = ("usb host busy: worker threads of closed sessions are still inside the backend; "
                     "try again when they finish")

ReplySink = Callable[[Frame], None]


@dataclass(frozen=True)
class WorkerLimits:
    """Bounds for one session's worker.

    ``max_pending``: frames waiting to be served (None: the session's
    ``frame_budget``). ``idle_s``: how long an idle lane thread lingers.
    ``join_timeout_s``: how long :meth:`UsbSessionWorker.close` waits.
    ``max_abandoned``: process-wide count of threads left inside the backend
    by closed sessions at which new claims are refused.
    """

    max_pending: Optional[int] = None
    idle_s: float = DEFAULT_IDLE_S
    join_timeout_s: float = DEFAULT_JOIN_TIMEOUT_S
    max_abandoned: int = DEFAULT_MAX_ABANDONED


class _AbandonedThreads:
    """Lane threads that outlived their session's close, still inside a backend call; never killed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._threads: Set[threading.Thread] = set()

    def add(self, threads: List[threading.Thread]) -> None:
        with self._lock:
            self._threads.update(threads)

    def count(self) -> int:
        """How many are still running (finished ones are forgotten here)."""
        with self._lock:
            self._threads = {thread for thread in self._threads if thread.is_alive()}
            return len(self._threads)


_ABANDONED = _AbandonedThreads()


def abandoned_worker_threads() -> int:
    """Lane threads of closed USB sessions, in this process, still inside a backend call."""
    return _ABANDONED.count()


class _Lane:
    """One FIFO of frames, served by at most one thread at a time."""

    __slots__ = ("key", "frames", "wakeup", "thread")

    def __init__(self, key: int, lock: threading.Lock) -> None:
        self.key = key
        self.frames: Deque[Frame] = deque()
        self.wakeup = threading.Condition(lock)
        self.thread: Optional[threading.Thread] = None


class UsbSessionWorker:
    """Serve one session's frames on worker threads, one lane per claim."""

    def __init__(self, session: UsbPassthroughSession, send_reply: ReplySink,
                 limits: Optional[WorkerLimits] = None) -> None:
        limits = limits or WorkerLimits()
        self._session = session
        self._send_reply = send_reply
        budget = session.frame_budget if limits.max_pending is None else limits.max_pending
        self._max_pending = max(1, int(budget))
        self._idle_s = max(0.0, float(limits.idle_s))
        self._join_timeout_s = max(0.0, float(limits.join_timeout_s))
        self._max_abandoned = max(1, int(limits.max_abandoned))
        self._lock = threading.Lock()
        self._lanes: Dict[int, _Lane] = {}
        self._pending = 0
        self._closed = False

    @property
    def pending(self) -> int:
        """Frames queued and not yet being served."""
        with self._lock:
            return self._pending

    @property
    def closed(self) -> bool:
        """True once :meth:`close` has run; later frames are refused."""
        with self._lock:
            return self._closed

    def submit(self, frame: Frame) -> Optional[str]:
        """Queue ``frame`` without blocking; None if accepted, else why not."""
        key = self._lane_key(frame)
        if frame.op in _NEW_CLAIM_OPCODES and _ABANDONED.count() >= self._max_abandoned:
            return ABANDONED_MESSAGE
        with self._lock:
            if self._closed:
                return CLOSED_MESSAGE
            if self._pending >= self._max_pending:
                return QUEUE_FULL_MESSAGE
            lane = self._lanes.get(key)
            if lane is None:
                lane = self._lanes[key] = _Lane(key, self._lock)
            lane.frames.append(frame)
            self._pending += 1
            if lane.thread is not None:
                lane.wakeup.notify()
                return None
            return self._start_lane_locked(lane)

    def _start_lane_locked(self, lane: _Lane) -> Optional[str]:
        """Give ``lane`` its thread; on failure take its last frame back."""
        thread = threading.Thread(
            target=self._serve_lane, args=(lane,), daemon=True,
            name=f"usb-passthrough-lane-{lane.key}",
        )
        try:
            thread.start()
        except RuntimeError as error:   # the interpreter is out of threads
            autocontrol_logger.error("usb passthrough worker: cannot start a thread: %r", error)
            lane.frames.pop()
            self._pending -= 1
            if not lane.frames:
                del self._lanes[lane.key]
            return NO_WORKER_MESSAGE
        lane.thread = thread
        return None

    def close(self) -> None:
        """Drop queued frames, release every claim, join threads (bounded)."""
        with self._lock:
            first = not self._closed
            self._closed = True
            lanes = list(self._lanes.values())
            for lane in lanes:
                lane.frames.clear()
                lane.wakeup.notify_all()
            self._pending = 0
            threads = [lane.thread for lane in lanes if lane.thread is not None]
        self._session.close_all()
        if first:
            self._join(threads)

    # --- internals ----------------------------------------------------------

    def _lane_key(self, frame: Frame) -> int:
        if frame.op in _CLAIM_OPCODES and self._session.has_claim(frame.claim_id):
            return int(frame.claim_id)
        return _SESSION_LANE

    def _serve_lane(self, lane: _Lane) -> None:
        linger = True
        while True:
            frame = self._next_frame(lane, linger)
            if frame is None:
                return
            self._deliver(self._handle(frame))
            linger = lane.key == _SESSION_LANE or self._session.has_claim(lane.key)

    def _next_frame(self, lane: _Lane, linger: bool) -> Optional[Frame]:
        with self._lock:
            if linger and not self._closed and not lane.frames:
                lane.wakeup.wait_for(lambda: self._closed or bool(lane.frames), self._idle_s)
            if self._closed or not lane.frames:
                lane.thread = None
                if self._lanes.get(lane.key) is lane:
                    del self._lanes[lane.key]
                return None
            self._pending -= 1
            return lane.frames.popleft()

    def _handle(self, frame: Frame) -> List[Frame]:
        try:
            return self._session.handle_frame(frame)
        except Exception as error:  # noqa: BLE001  # pylint: disable=broad-except  # reason: one faulty frame must not kill the lane; the viewer gets an ERROR
            autocontrol_logger.error("usb passthrough worker: handle_frame raised %r", error)
            return self._session.refuse(frame, f"internal error: {error}", strike=False)

    def _deliver(self, replies: List[Frame]) -> None:
        if self.closed:
            return  # the viewer is gone; a late result is discarded
        for reply in replies:
            try:
                self._send_reply(reply)
            except Exception as error:  # noqa: BLE001  # pylint: disable=broad-except  # reason: a send to a dying channel must not kill the lane
                autocontrol_logger.warning("usb passthrough worker: reply send failed: %r", error)
                return

    def _join(self, threads: List[threading.Thread]) -> None:
        deadline = time.monotonic() + self._join_timeout_s
        current = threading.current_thread()
        for thread in threads:
            if thread is not current:
                thread.join(max(0.0, deadline - time.monotonic()))
        stuck = [thread for thread in threads if thread is not current and thread.is_alive()]
        if stuck:
            _ABANDONED.add(stuck)
            autocontrol_logger.warning(
                "usb passthrough: %d worker(s) still inside the backend after close; "
                "their results will be discarded and their handles closed", len(stuck),
            )


__all__ = ["UsbSessionWorker", "WorkerLimits", "abandoned_worker_threads"]
