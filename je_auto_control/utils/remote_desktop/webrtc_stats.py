"""Polling helper that turns aiortc's ``RTCStats`` reports into a small dict.

Used by the viewer GUI to render a translucent overlay (RTT, FPS, bitrate,
loss). Aiortc reports stats per stream; we aggregate the inbound video
stream's deltas across polls and expose the rolling rate.
"""
from __future__ import annotations

import asyncio
import time
import threading
from concurrent.futures import Future
from enum import Enum, auto
from dataclasses import asdict, dataclass
from typing import Callable, Optional

from je_auto_control.utils.logging.logging_instance import autocontrol_logger


_DEFAULT_INTERVAL_S = 1.0


@dataclass
class StatsSnapshot:
    """One sample's worth of derived metrics."""
    rtt_ms: Optional[float] = None
    fps: Optional[float] = None
    bitrate_kbps: Optional[float] = None
    packet_loss_pct: Optional[float] = None
    jitter_ms: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


class _PollState(Enum):
    NEW = auto()
    SUBMITTING = auto()
    RUNNING = auto()
    STOPPED = auto()


class StatsPoller:
    """Drive a periodic ``getStats()`` poll on the asyncio bridge."""

    def __init__(self, pc, callback: Callable[[StatsSnapshot], None],
                 interval_s: float = _DEFAULT_INTERVAL_S) -> None:
        self._pc = pc
        self._callback: Optional[Callable[[StatsSnapshot], None]] = callback
        self._interval = max(0.25, float(interval_s))
        self._lifecycle_lock = threading.Lock()
        self._state = _PollState.NEW
        self._future: Optional[Future[None]] = None
        self._prev_packets_received = 0
        self._prev_packets_lost = 0
        self._prev_bytes_received = 0
        self._prev_frames_decoded = 0
        self._prev_sample_time: Optional[float] = None

    @property
    def _stopped(self) -> bool:
        return self._state is _PollState.STOPPED

    def start(self) -> None:
        """Submit polling once without waiting for the bridge to run it.

        Stop is terminal. A submission already in progress is cancelled as
        soon as its future arrives; duplicate starts cannot submit another loop.
        """
        with self._lifecycle_lock:
            if self._state is not _PollState.NEW:
                return
            self._state = _PollState.SUBMITTING
        coroutine = self._loop()
        try:
            from je_auto_control.utils.remote_desktop.webrtc_transport import get_bridge
            future = get_bridge().submit(coroutine)
        except BaseException as error:  # reason: release unsubmitted coroutine; only expected bridge errors are logged
            coroutine.close()
            with self._lifecycle_lock:
                if self._state is _PollState.SUBMITTING:
                    self._state = _PollState.NEW
            if not isinstance(error, (RuntimeError, OSError)):
                raise
            autocontrol_logger.warning("stats poller start: %r", error)
            return
        with self._lifecycle_lock:
            stopped = self._stopped
            if not stopped:
                self._state = _PollState.RUNNING
                self._future = future
        future.add_done_callback(self._finished)
        if stopped:
            future.cancel()

    def _finished(self, future: Future[None]) -> None:
        with self._lifecycle_lock:
            self._state = _PollState.STOPPED
            self._callback = None
            if self._future is future:
                self._future = None
        if not future.cancelled():
            error = future.exception()
            if error is not None:
                autocontrol_logger.warning("stats poller: %r", error)

    def stop(self) -> None:
        """Retire this poller without joining, waiting or acquiring a bridge.

        Samples finishing after stop are discarded. A callback already admitted
        may finish; stop does not preempt application callback code.
        """
        with self._lifecycle_lock:
            self._state = _PollState.STOPPED
            self._callback = None
            future, self._future = self._future, None
        if future is not None:
            future.cancel()

    async def _loop(self) -> None:
        # No try/except CancelledError wrapper here — cancellation must
        # propagate to the awaiter so callers know the loop ended due
        # to cancellation rather than completing normally (S7497).
        while not self._stopped:
            await asyncio.sleep(self._interval)
            if self._stopped:
                return
            try:
                snapshot = await self._sample()
            except (RuntimeError, OSError) as error:
                autocontrol_logger.debug("stats sample: %r", error)
                continue
            if self._stopped:
                return
            if snapshot is not None:
                self._deliver(snapshot)

    def _deliver(self, snapshot: StatsSnapshot) -> None:
        """Keep callback ownership out of the polling coroutine's suspended frame."""
        callback = self._callback
        if callback is not None and not self._stopped:
            try:
                callback(snapshot)
            except (RuntimeError, OSError) as error:
                autocontrol_logger.debug("stats cb: %r", error)

    async def _sample(self) -> Optional[StatsSnapshot]:
        if self._pc is None:
            return None
        report = await self._pc.getStats()
        snap = StatsSnapshot()
        now = time.monotonic()
        delta_t = (now - self._prev_sample_time) if self._prev_sample_time else None
        self._prev_sample_time = now
        for entry in report.values():
            self._absorb_entry(entry, delta_t, snap)
        return snap

    def _absorb_entry(self, entry, delta_t,
                      snap: StatsSnapshot) -> None:
        stat_type = getattr(entry, "type", None)
        if stat_type == "inbound-rtp" and getattr(entry, "kind", "") == "video":
            self._update_inbound(entry, delta_t, snap)
        elif stat_type == "remote-inbound-rtp":
            self._absorb_remote_inbound(entry, snap)
        elif stat_type == "candidate-pair":
            rtt = getattr(entry, "currentRoundTripTime", None)
            if rtt is not None and snap.rtt_ms is None:
                snap.rtt_ms = float(rtt) * 1000.0

    @staticmethod
    def _absorb_remote_inbound(entry, snap: StatsSnapshot) -> None:
        rtt = getattr(entry, "roundTripTime", None)
        if rtt is not None:
            snap.rtt_ms = float(rtt) * 1000.0
        jitter = getattr(entry, "jitter", None)
        if jitter is not None:
            snap.jitter_ms = float(jitter) * 1000.0

    @staticmethod
    def _int_attr(entry, name: str) -> int:
        """Read a numeric WebRTC stat attribute as an int (missing -> 0)."""
        return int(getattr(entry, name, 0) or 0)

    def _update_inbound(self, entry, delta_t, snap: StatsSnapshot) -> None:
        bytes_received = self._int_attr(entry, "bytesReceived")
        frames_decoded = self._int_attr(entry, "framesDecoded")
        packets_received = self._int_attr(entry, "packetsReceived")
        packets_lost = self._int_attr(entry, "packetsLost")
        self._update_rates(bytes_received, frames_decoded, delta_t, snap)
        self._update_packet_loss(packets_received, packets_lost, snap)
        self._prev_bytes_received = bytes_received
        self._prev_frames_decoded = frames_decoded
        self._prev_packets_received = packets_received
        self._prev_packets_lost = packets_lost

    def _update_rates(self, bytes_received: int, frames_decoded: int,
                      delta_t, snap: StatsSnapshot) -> None:
        """Derive bitrate + fps from inter-sample deltas."""
        if not delta_t or delta_t <= 0:
            return
        byte_delta = bytes_received - self._prev_bytes_received
        if byte_delta >= 0:
            snap.bitrate_kbps = (byte_delta * 8 / 1000.0) / delta_t
        frame_delta = frames_decoded - self._prev_frames_decoded
        if frame_delta >= 0:
            snap.fps = frame_delta / delta_t

    def _update_packet_loss(self, packets_received: int, packets_lost: int,
                            snap: StatsSnapshot) -> None:
        """Derive recent packet-loss percentage from inter-sample deltas."""
        total = packets_received + packets_lost
        if total <= 0:
            return
        recent_lost = packets_lost - self._prev_packets_lost
        recent_total = (packets_received + packets_lost
                        - self._prev_packets_received
                        - self._prev_packets_lost)
        if recent_total > 0:
            snap.packet_loss_pct = (recent_lost / recent_total) * 100.0


__all__ = ["StatsSnapshot", "StatsPoller"]
