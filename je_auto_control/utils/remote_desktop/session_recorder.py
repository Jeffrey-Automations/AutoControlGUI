"""Record incoming WebRTC video frames to an mp4 file via PyAV.

The viewer's frame callback fires on the asyncio thread. ``SessionRecorder``
is thread-safe: ``write_frame`` may be called from that thread while
``stop`` is called from the Qt thread. Only one open recording per
instance. Create a new recorder after stopping.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, Tuple

try:
    import av
except ImportError as exc:  # pragma: no cover - 'webrtc' extra
    raise ImportError(
        "Session recording requires the 'webrtc' extra (PyAV).",
    ) from exc

from je_auto_control.utils.exception.control_signals import raise_caused_run_interruption
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.remote_desktop.media_retirement import (
    Completion, RetirementStatus, require_retired,
)


_DEFAULT_CODEC = "libx264"
_DEFAULT_PIXEL_FORMAT = "yuv420p"

# Map container suffix → codec/pix_fmt overrides for that container.
_FORMAT_PRESETS = {
    "mp4": {"codec": "libx264", "pixel_format": "yuv420p"},
    "webm": {"codec": "libvpx-vp9", "pixel_format": "yuv420p"},
    "mkv": {"codec": "libx264", "pixel_format": "yuv420p"},
}


def preset_for_path(path) -> dict:
    """Return codec defaults for a path's extension, or empty dict."""
    suffix = str(path).rsplit(".", 1)[-1].lower()
    return _FORMAT_PRESETS.get(suffix, {})


class SessionRecorder:
    """Mux incoming ``av.VideoFrame`` instances into an mp4 file."""

    def __init__(self, output_path: str, *,
                 codec: str = _DEFAULT_CODEC,
                 pixel_format: str = _DEFAULT_PIXEL_FORMAT,
                 fps: int = 24) -> None:
        self._path = Path(output_path)
        self._codec = codec
        self._pixel_format = pixel_format
        self._fps = max(1, int(fps))
        self._lock = threading.Lock()
        self._container: Optional["av.container.OutputContainer"] = None
        self._stream: Optional["av.video.stream.VideoStream"] = None
        self._started = False
        self._closed = False
        self._flush = Completion.PENDING
        self._release = Completion.PENDING
        self._close_attempted = False
        self._failures: tuple[str, ...] = ()

    def _open(self, frame) -> Tuple[
        "av.container.OutputContainer", "av.video.stream.VideoStream",
    ]:
        """Return the open (container, stream) pair, creating it on first use."""
        if self._container is not None and self._stream is not None:
            return self._container, self._stream
        self._path.parent.mkdir(parents=True, exist_ok=True)
        container = av.open(str(self._path), mode="w")
        self._container = container
        try:
            stream = container.add_stream(self._codec, rate=self._fps)
            if not isinstance(stream, av.video.stream.VideoStream):
                raise ValueError("session recording requires a video codec")
            stream.width = frame.width
            stream.height = frame.height
            stream.pix_fmt = self._pixel_format
        except BaseException:
            self._failures += ("recorder.setup",)
            raise
        self._container = container
        self._stream = stream
        self._started = True
        autocontrol_logger.info(
            "session_recorder: writing to %s (%dx%d @%dfps, %s)",
            self._path, frame.width, frame.height, self._fps, self._codec,
        )
        return container, stream

    def write_frame(self, frame) -> None:
        """Encode one ``av.VideoFrame``; lazy-init the container."""
        if self._closed:
            return
        with self._lock:
            if self._closed:
                return
            try:
                container, stream = self._open(frame)
                for packet in stream.encode(frame):
                    container.mux(packet)
            except BaseException as error:
                autocontrol_logger.warning(
                    "session_recorder: write failed, stopping: %r", error,
                )
                self._failures += ("recorder.write",)
                self._closed = True
                try:
                    self._teardown_locked()
                except BaseException:
                    raise_caused_run_interruption(error)
                    raise
                raise_caused_run_interruption(error)

    def stop(self) -> None:
        """Flush the encoder and close the file."""
        with self._lock:
            self._closed = True
            self._teardown_locked()
        require_retired(self)

    def _teardown_locked(self) -> None:
        flush_failure = self._flush_once()
        close_failure = self._close_once()
        for failure in (flush_failure, close_failure):
            if failure is not None:
                raise_caused_run_interruption(failure)

    def _flush_once(self) -> BaseException | None:
        if self._flush is not Completion.PENDING:
            return None
        self._flush = Completion.UNCERTAIN
        try:
            if self._stream is not None and self._container is not None:
                for packet in self._stream.encode(None):
                    self._container.mux(packet)
        except BaseException as error:  # reason: close independently before preserving interruption
            self._failures += ("recorder.flush",)
            return error
        self._flush = Completion.CONFIRMED
        return None

    def _close_once(self) -> BaseException | None:
        if self._close_attempted:
            return None
        # PyAV may mark _done after a failed trailer write; replay proves nothing.
        self._close_attempted = True
        try:
            if self._container is not None:
                self._container.close()
        except BaseException as error:  # reason: retain uncertain ownership before preserving interruption
            self._release = Completion.UNCERTAIN
            self._failures += ("recorder.close",)
            return error
        self._release = Completion.CONFIRMED
        self._container = None
        self._stream = None
        return None

    @property
    def retirement_status(self) -> RetirementStatus:
        with self._lock:
            finalized = self._flush
            if self._failures:
                finalized = Completion.UNCERTAIN
            return RetirementStatus(self._closed, self._release, finalized,
                                    False, self._failures)

    @property
    def is_active(self) -> bool:
        return self._started and not self._closed

    @property
    def has_output(self) -> bool:
        """Whether a frame arrived, so that the output file was created."""
        return self._started

    @property
    def output_path(self) -> Path:
        return self._path


__all__ = ["SessionRecorder"]
