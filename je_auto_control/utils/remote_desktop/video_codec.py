"""Phase 6.8: pluggable video codec for the TCP / WS frame path.

The capture loop produces JPEG frames by default. That's bandwidth-cheap
for static screens (Phase 2.3 dedup makes it ~free) but expensive for
fast motion. This module adds an opt-in H.264 encoder that reuses the
PyAV machinery already pulled in by the WebRTC stack — same `[webrtc]`
extra, no new dependency.

Wire format: host and viewer agree on a codec in the ``AUTH_OK`` JSON
payload. The FRAME body becomes a 1-byte codec tag + encoded bytes:

    0x01 jpeg   — body is the raw JPEG (default; backward compatible
                  with viewers that don't read the tag)
    0x02 h264   — body is one or more H.264 NAL units (Annex-B)
    0x03 hevc   — body is HEVC NAL units (Annex-B)

Pre-existing JPEG-only viewers don't see the tag because the host
falls back to raw-JPEG mode for the legacy clients (codec
negotiation in AUTH_OK absent → assume jpeg, no tag prefix).
"""
from __future__ import annotations

from typing import Any, Iterable, Iterator, Optional

from je_auto_control.utils.logging.logging_instance import autocontrol_logger

CODEC_JPEG = "jpeg"
CODEC_H264 = "h264"
CODEC_HEVC = "hevc"

_CODEC_TAGS = {
    CODEC_JPEG: 0x01,
    CODEC_H264: 0x02,
    CODEC_HEVC: 0x03,
}
_TAGS_TO_CODEC = {v: k for k, v in _CODEC_TAGS.items()}
_START_CODE = b"\x00\x00\x01"
_H264_IDR = 5
_HEVC_IRAP = (16, 21)


def codec_tag(name: str) -> int:
    """Return the 1-byte wire tag for a codec name."""
    if name not in _CODEC_TAGS:
        raise ValueError(f"unknown codec: {name!r}")
    return _CODEC_TAGS[name]


def codec_from_tag(tag: int) -> str:
    """Return the codec name for a wire tag byte."""
    if tag not in _TAGS_TO_CODEC:
        raise ValueError(f"unknown codec tag: 0x{tag:02x}")
    return _TAGS_TO_CODEC[tag]


def _annexb_nal_headers(packet: bytes) -> Iterator[int]:
    """Yield the first header byte of each NAL unit in an Annex-B byte stream."""
    position = packet.find(_START_CODE)
    while 0 <= position < len(packet) - len(_START_CODE):
        yield packet[position + len(_START_CODE)]
        position = packet.find(_START_CODE, position + len(_START_CODE))


def is_keyframe_packet(codec: str, packet: bytes) -> bool:
    """Whether a decoder can start at ``packet`` without any earlier one.

    JPEG frames always can. An H.264 packet can when it holds an IDR slice
    (NAL type 5), an HEVC one when it holds an IRAP picture (types 16-21);
    a packet in any other codec is never taken to be one.
    """
    if codec == CODEC_JPEG:
        return True
    if codec == CODEC_H264:
        return any(header & 0x1F == _H264_IDR for header in _annexb_nal_headers(packet))
    if codec == CODEC_HEVC:
        return any(_HEVC_IRAP[0] <= (header >> 1) & 0x3F <= _HEVC_IRAP[1]
                   for header in _annexb_nal_headers(packet))
    return False


class CodecProvider:
    """Abstract: convert raw frames into wire-ready encoded packets.

    The host's capture loop calls :meth:`encode_jpeg` for every JPEG
    that came out of the frame provider. ``yield`` zero or more
    packets — typically one per input frame for I-frame codecs, but
    P-frame codecs may emit nothing if the encoder is still buffering.
    """

    name: str = "raw"

    def encode_jpeg(self, jpeg_bytes: bytes) -> Iterable[bytes]:
        """Yield wire-ready packets for one captured JPEG."""
        raise NotImplementedError

    def request_keyframe(self) -> bool:
        """Ask for the next encoded frame to be a keyframe.

        Called on the capture thread when a viewer has to resynchronise.
        ``True`` when the provider will honour it; the default cannot, and
        such a viewer then waits for the encoder's next natural keyframe.
        """
        return False

    def is_keyframe(self, packet: bytes) -> bool:
        """Whether a viewer can start decoding at ``packet``; see :func:`is_keyframe_packet`."""
        return is_keyframe_packet(self.name, packet)

    def close(self) -> None:
        """Release encoder resources. Idempotent."""


class JpegPassthrough(CodecProvider):
    """Default codec: emit the JPEG verbatim, one packet per frame."""

    name = CODEC_JPEG

    def encode_jpeg(self, jpeg_bytes: bytes) -> Iterable[bytes]:
        return [jpeg_bytes] if jpeg_bytes else []


class H264CodecProvider(CodecProvider):
    """libx264 encoder via PyAV. Imports ``av`` lazily.

    Raises :class:`ImportError` from the constructor when PyAV is not
    installed. Operators trigger this provider by passing
    ``codec_provider=H264CodecProvider(...)`` to :class:`RemoteDesktopHost`;
    the legacy default (JPEG) keeps working without the extras.
    """

    name = CODEC_H264

    def __init__(self,
                 *, fps: int = 30, bitrate: int = 4_000_000,
                 width: Optional[int] = None,
                 height: Optional[int] = None,
                 gop_size: int = 60) -> None:
        try:
            import av  # noqa: F401  imported for the import check
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "H.264 codec requires the 'webrtc' extra: "
                "pip install je_auto_control[webrtc]",
            ) from exc
        self._fps = int(fps)
        self._bitrate = int(bitrate)
        self._width = width
        self._height = height
        self._gop_size = int(gop_size)
        self._container: Optional[Any] = None
        self._stream: Optional[Any] = None
        self._closed = False
        self._force_keyframe = False

    def _ensure_stream(self, width: int, height: int) -> Any:
        """Return the encoder stream, opening the container on first use."""
        if self._stream is not None:
            return self._stream
        import av
        import io
        self._buffer = io.BytesIO()
        # ``annexb`` ensures NAL units are emitted with the standard
        # ``00 00 00 01`` start codes so a viewer can hand the bytes
        # straight to a hardware decoder.
        self._container = av.open(self._buffer, mode="w", format="h264")
        stream = self._container.add_stream("h264", rate=self._fps)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        stream.bit_rate = self._bitrate
        stream.options = {
            "preset": "veryfast",
            "tune": "zerolatency",
            "g": str(self._gop_size),
            # A forced I-frame is an IDR, so the frames after it never
            # reference one a resynchronising viewer did not get.
            "forced-idr": "1",
        }
        self._stream = stream
        return stream

    def encode_jpeg(self, jpeg_bytes: bytes) -> Iterable[bytes]:
        if self._closed or not jpeg_bytes:
            return ()
        import av  # noqa: F401  lazy keep
        from io import BytesIO
        from PIL import Image
        image: Image.Image = Image.open(BytesIO(jpeg_bytes))
        if image.mode != "RGB":
            image = image.convert("RGB")
        # yuv420p needs even dimensions: libx264 refused to open for a
        # 101x75 frame. The odd last row / column is dropped.
        width, height = image.width & ~1, image.height & ~1
        if width < 2 or height < 2:
            return ()
        if (width, height) != image.size:
            image = image.crop((0, 0, width, height))
        stream = self._ensure_stream(width, height)
        frame = av.VideoFrame.from_image(image)
        if (width, height) != (stream.width, stream.height):
            frame = frame.reformat(width=stream.width, height=stream.height)
        frame.pts = None
        if self._force_keyframe:
            self._force_keyframe = False
            frame.pict_type = av.video.frame.PictureType.I
        return [bytes(packet) for packet in stream.encode(frame)]

    def request_keyframe(self) -> bool:
        """Make the next encoded frame an IDR; see :meth:`CodecProvider.request_keyframe`."""
        self._force_keyframe = True
        return True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        import av
        errors = (ValueError, RuntimeError, av.FFmpegError)
        try:
            if self._stream is not None:
                # Drain remaining buffered packets — PyAV requires iterating
                # ``encode(None)`` to flush trailing frames before close.
                for _packet in self._stream.encode(None):
                    del _packet
        except errors as error:
            autocontrol_logger.info("H.264 flush failed: %r", error)
        finally:
            # Closed even when the flush failed: an encoder that never
            # opened left the container open.
            if self._container is not None:
                try:
                    self._container.close()
                except errors as error:
                    autocontrol_logger.info("H.264 container close failed: %r", error)


def is_h264_available() -> bool:
    """Return True iff PyAV is importable in the current process."""
    try:
        import av  # noqa: F401
    except ImportError:
        return False
    return True


__all__ = [
    "CODEC_JPEG", "CODEC_H264", "CODEC_HEVC",
    "CodecProvider", "JpegPassthrough", "H264CodecProvider",
    "codec_tag", "codec_from_tag", "is_h264_available", "is_keyframe_packet",
]
