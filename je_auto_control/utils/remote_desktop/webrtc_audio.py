"""Aiortc audio track for the viewer mic uplink.

Lets aiortc encode the mic stream as Opus (~6× smaller than the raw
PCM-over-DataChannel path in :mod:`webrtc_mic`). Capture stays on
sounddevice via :class:`AudioCapture`; we just bridge the int16 PCM
blocks into ``av.AudioFrame`` objects that aiortc consumes.

Usage on the viewer side:
  * Host adds a recvonly audio transceiver in its offer.
  * Viewer attaches a :class:`OpusMicAudioTrack` to that transceiver
    before ``createAnswer``; aiortc negotiates Opus.
  * Host receives via ``pc.on('track')`` for ``kind == 'audio'``,
    decodes frames, and feeds ``AudioPlayer`` (see
    :class:`OpusMicReceiver`).
"""
from __future__ import annotations

import asyncio
import fractions
import threading
from typing import Any, Optional

try:
    import av
    from av.error import FFmpegError
    import numpy as np
    from aiortc import MediaStreamTrack
except ImportError as exc:  # pragma: no cover - optional dep
    raise ImportError(
        "Opus audio uplink requires the 'webrtc' extra (aiortc + av).",
    ) from exc

from je_auto_control.utils.exception.control_signals import raise_caused_run_interruption
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.remote_desktop.media_retirement import (
    Completion, RetirementStatus, require_retired, raise_cleanup_failures,
)
from je_auto_control.utils.remote_desktop.audio import (
    AudioBackendError, AudioCapture, AudioPlayer, is_audio_backend_available,
)


_DEFAULT_SAMPLE_RATE = 48000  # Opus's preferred rate
_DEFAULT_CHANNELS = 1
_BLOCK_FRAMES = 960  # 20 ms @ 48 kHz


class OpusMicAudioTrack(MediaStreamTrack):
    """Pulls int16 PCM blocks from sounddevice and emits ``av.AudioFrame``.

    The capture thread blocks on sounddevice; ``recv`` blocks on an
    asyncio ``Queue`` that the capture callback feeds. aiortc handles
    Opus encoding / packetization downstream.
    """
    kind = "audio"

    def __init__(self, sample_rate: int = _DEFAULT_SAMPLE_RATE,
                 channels: int = _DEFAULT_CHANNELS,
                 device: Optional[int] = None) -> None:
        super().__init__()
        if not is_audio_backend_available():
            raise AudioBackendError(
                "sounddevice not available; install with pip install sounddevice",
            )
        self._sample_rate = sample_rate
        self._channels = channels
        self._device = device
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self._timestamp = 0
        self._capture: Optional[AudioCapture] = None
        self._lock = threading.Lock()
        self._start_capture()

    def _start_capture(self) -> None:
        with self._lock:
            if self._capture is not None:
                return
            self._capture = AudioCapture(
                on_block=self._on_block,
                device=self._device,
                sample_rate=self._sample_rate,
                channels=self._channels,
                block_frames=_BLOCK_FRAMES,
            )
            self._capture.start()
        autocontrol_logger.info(
            "OpusMicAudioTrack: capture started (%d Hz)", self._sample_rate,
        )

    def _on_block(self, pcm_bytes: bytes) -> None:
        if self.readyState == "ended":
            return
        # Called from the sounddevice thread.
        try:
            self._loop.call_soon_threadsafe(self._enqueue, pcm_bytes)
        except RuntimeError as error:
            raise_caused_run_interruption(error)

    def _enqueue(self, pcm_bytes: bytes) -> None:
        if self.readyState == "ended":
            return
        if self._queue.full():
            try:
                self._queue.get_nowait()  # drop oldest to keep latency bounded
            except asyncio.QueueEmpty:
                pass
        try:
            self._queue.put_nowait(pcm_bytes)
        except asyncio.QueueFull:
            pass

    async def recv(self) -> "av.AudioFrame":
        from aiortc.mediastreams import MediaStreamError
        if self.readyState == "ended":
            raise MediaStreamError
        pcm_bytes = await self._queue.get()
        if pcm_bytes is None or self.readyState == "ended":
            raise MediaStreamError
        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        # av.AudioFrame.from_ndarray expects shape (channels, samples) for
        # planar layouts; for "s16" (interleaved) it expects (1, total).
        layout = "mono" if self._channels == 1 else "stereo"
        frame = av.AudioFrame.from_ndarray(
            samples.reshape(1, -1), format="s16", layout=layout,
        )
        frame.sample_rate = self._sample_rate
        frame.pts = self._timestamp
        frame.time_base = fractions.Fraction(1, self._sample_rate)
        self._timestamp += samples.shape[0] // self._channels
        return frame

    def _end_queue(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(None)

    @property
    def retirement_status(self) -> RetirementStatus:
        if self._capture is not None:
            return self._capture.retirement_status
        return RetirementStatus(self.readyState == "ended", Completion.CONFIRMED,
                                Completion.CONFIRMED)

    def stop(self) -> None:
        failures = []
        try:
            super().stop()
        except BaseException as error:  # reason: attempt independent child cleanup before preserving failures
            failures.append(error)
        try:
            if not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._end_queue)
        except BaseException as error:  # reason: attempt independent child cleanup before preserving failures
            failures.append(error)
        try:
            with self._lock:
                if self._capture is not None:
                    self._capture.stop()
                    self._capture = None
        except BaseException as error:  # reason: attempt independent child cleanup before preserving failures
            failures.append(error)
        raise_cleanup_failures(failures)


class OpusMicReceiver:
    """Host-side: pull frames from the incoming audio track and play them."""

    def __init__(self, sample_rate: int = _DEFAULT_SAMPLE_RATE,
                 channels: int = _DEFAULT_CHANNELS,
                 device: Optional[int] = None) -> None:
        if not is_audio_backend_available():
            raise AudioBackendError(
                "sounddevice not available; install with pip install sounddevice",
            )
        self._sample_rate = sample_rate
        self._channels = channels
        self._player = AudioPlayer(
            device=device, sample_rate=sample_rate, channels=channels,
        )
        self._player.start()
        self._task: Optional[asyncio.Task] = None
        self._stopped = False
        self._player_retired = False
        self._resampler: Optional[Any] = None

    def consume(self, track) -> None:
        """Spawn a background task that drains ``track.recv()`` into the player."""
        if self._stopped:
            raise AudioBackendError("audio receiver is stopped")
        if self._task is not None:
            return
        self._task = asyncio.ensure_future(self._loop(track))

    async def _loop(self, track) -> None:
        from aiortc.mediastreams import MediaStreamError
        try:
            while not self._stopped:
                frame = await track.recv()
                if self._stopped or not bool(self._player.is_running):
                    return
                for chunk in self._to_player_pcm(frame):
                    self._player.play(chunk)
        except (asyncio.CancelledError, MediaStreamError):
            autocontrol_logger.info("opus mic receiver ended")
        except (OSError, RuntimeError) as error:
            raise_caused_run_interruption(error)
            autocontrol_logger.info("opus mic receiver ended: %r", error)

    def _to_player_pcm(self, frame) -> list:
        """int16 PCM in the player's layout and rate.

        aiortc's Opus decoder always yields 48 kHz stereo; written as is to a
        mono player it played at half speed and twice the length.
        """
        if self._resampler is None:
            self._resampler = av.AudioResampler(
                format="s16", layout="mono" if self._channels == 1 else "stereo",
                rate=self._sample_rate,
            )
        try:
            converted = self._resampler.resample(frame)
        except (TypeError, ValueError, RuntimeError, FFmpegError) as error:  # TypeError: not an AudioFrame
            raise_caused_run_interruption(error)
            autocontrol_logger.debug("audio frame resample: %r", error)
            return []
        chunks = []
        for out in converted:
            arr = out.to_ndarray()
            if arr.dtype != np.int16:
                arr = arr.astype(np.int16)
            chunks.append(arr.tobytes())
        return chunks

    @property
    def retirement_status(self) -> RetirementStatus:
        if not self._player_retired:
            return self._player.retirement_status
        pending = self._task is not None and not self._task.done()
        closed_loop = pending and self._task is not None and self._task.get_loop().is_closed()
        resources = Completion.CONFIRMED
        if pending:
            resources = Completion.UNCERTAIN if closed_loop else Completion.PENDING
        return RetirementStatus(self._stopped, resources,
                                Completion.CONFIRMED, pending and not closed_loop,
                                ("audio.task_pending",) if pending else ())

    def stop(self) -> None:
        self._stopped = True
        failures = []
        try:
            self._cancel_task()
        except BaseException as error:  # reason: attempt independent child cleanup before preserving failures
            failures.append(error)
        try:
            if not self._player_retired:
                self._player.stop()
                self._player_retired = True
        except BaseException as error:  # reason: attempt independent child cleanup before preserving failures
            failures.append(error)
        raise_cleanup_failures(failures)
        require_retired(self)

    def _cancel_task(self) -> None:
        if self._task is None:
            return
        if self._task.done():
            task, self._task = self._task, None
            if not task.cancelled():
                task.result()
            return
        loop = self._task.get_loop()
        if not loop.is_closed():
            loop.call_soon_threadsafe(self._task.cancel)


__all__ = ["OpusMicAudioTrack", "OpusMicReceiver"]
