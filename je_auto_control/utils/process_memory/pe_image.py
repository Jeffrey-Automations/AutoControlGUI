"""Derive complete executable-range checks from a pinned, supported PE32+ baseline."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import struct

from .models import FailureReason, MemoryObservationError
from .windows_launch import PinnedExecutable

_EXECUTE, _WRITE, _READ = 0x20000000, 0x80000000, 0x40000000
_MAX_FILE, _MAX_IMAGE, _MAX_CHECKED = 64 << 20, 64 << 20, 1 << 20
_PLAN_TOKEN = object()


def _require(condition: bool) -> None:
    if not condition:
        raise MemoryObservationError(FailureReason.UNSUPPORTED)


def _u32(raw: bytes, offset: int) -> int:
    _require(0 <= offset <= len(raw) - 4)
    return struct.unpack_from("<I", raw, offset)[0]


def _aligned(size: int, alignment: int) -> int:
    return (size + alignment - 1) // alignment * alignment


@dataclass(frozen=True)
class ImageRange:
    """Private loaded-image offset and size with the pinned baseline digest."""

    rva: int = field(repr=False)
    size: int
    sha256: str = field(repr=False)


@dataclass(frozen=True, init=False)
class ImageCodePlan:
    """Parser-derived coverage; no caller-selected addresses or live-process baseline."""

    executable: str
    version: str
    image_sha256: str = field(repr=False)
    image_size: int
    ranges: tuple[ImageRange, ...] = field(repr=False)

    def __init__(self, executable: str, version: str, image_sha256: str, image_size: int,
                 ranges: tuple[ImageRange, ...], *, _token: object = None) -> None:
        _require(_token is _PLAN_TOKEN)
        names = ("executable", "version", "image_sha256", "image_size", "ranges")
        for name, value in zip(names, (executable, version, image_sha256, image_size, ranges)):
            object.__setattr__(self, name, value)

    @property
    def checked_bytes(self) -> int:
        """Bytes that every verification must charge to its reader's existing budget."""
        return sum(item.size for item in self.ranges)


@dataclass(frozen=True)
class _Section:
    rva: int
    size: int
    raw_offset: int
    raw_size: int
    flags: int
    virtual_size: int


@dataclass(frozen=True)
class _Layout:
    image_size: int
    header_size: int
    entry: int
    sections: tuple[_Section, ...]
    relocations: tuple[int, int]
    imports: tuple[int, int]


def _headers(raw: bytes) -> tuple[int, int, int, int]:
    _require(len(raw) >= 64 and raw[:2] == b"MZ")
    offset = _u32(raw, 60)
    _require(64 <= offset <= min(65536, len(raw) - 264))
    _require(raw[offset:offset + 4] == b"PE\0\0")
    machine, count, _, _, _, size, flags = struct.unpack_from("<HHIIIHH", raw, offset + 4)
    _require(machine == 0x8664 and 1 <= count <= 96 and size == 240)
    _require(bool(flags & 2) and not flags & 0x2000)
    optional = offset + 24
    _require(struct.unpack_from("<H", raw, optional)[0] == 0x20B)
    _require(_u32(raw, optional + 108) == 16)
    return optional, optional + size, count, _u32(raw, optional + 16)


def _alignment(raw: bytes, optional: int) -> tuple[int, int]:
    section, file = _u32(raw, optional + 32), _u32(raw, optional + 36)
    _require(4096 <= section <= 65536 and section & (section - 1) == 0)
    _require(512 <= file <= section and file & (file - 1) == 0)
    return section, file


def _section(raw: bytes, offset: int, alignment: tuple[int, int],
             sizes: tuple[int, int]) -> _Section:
    section_alignment, file_alignment = alignment
    image_size, header_size = sizes
    virtual, rva, raw_size, raw_offset = struct.unpack_from("<IIII", raw, offset + 8)
    flags = _u32(raw, offset + 36)
    size = _aligned(max(virtual, raw_size), section_alignment)
    _require(size > 0 and rva % section_alignment == 0)
    _require(rva >= _aligned(header_size, section_alignment) and rva + size <= image_size)
    if raw_size:
        _require(raw_offset >= header_size and raw_offset % file_alignment == 0)
        _require(raw_size % file_alignment == 0 and raw_offset + raw_size <= len(raw))
    return _Section(rva, size, raw_offset, raw_size, flags, virtual)


def _sections(raw: bytes, table: int, count: int, alignment: tuple[int, int],
              sizes: tuple[int, int]) -> tuple[_Section, ...]:
    result = [_section(raw, table + index * 40, alignment, sizes) for index in range(count)]
    _nonoverlap([(item.rva, item.size) for item in result])
    _nonoverlap([(item.raw_offset, item.raw_size) for item in result if item.raw_size])
    return tuple(result)


def _nonoverlap(ranges: list[tuple[int, int]]) -> None:
    ordered = sorted(ranges)
    pairs = zip(ordered, ordered[1:])
    _require(all(start + size <= following for (start, size), (following, _) in pairs))


def _layout(raw: bytes) -> _Layout:
    optional, table, count, entry = _headers(raw)
    alignment = _alignment(raw, optional)
    image, header = _u32(raw, optional + 56), _u32(raw, optional + 60)
    _require(0 < image <= _MAX_IMAGE and image % alignment[0] == 0)
    _require(table + count * 40 <= header <= min(len(raw), 65536) and header % alignment[1] == 0)
    sections = _sections(raw, table, count, alignment, (image, header))
    relocations = struct.unpack_from("<II", raw, optional + 112 + 5 * 8)
    imports = struct.unpack_from("<II", raw, optional + 112 + 12 * 8)
    return _Layout(image, header, entry, sections, relocations, imports)


def _overlaps(rva: int, size: int, protected: tuple[ImageRange, ...]) -> bool:
    return any(rva < item.rva + item.size and item.rva < rva + size for item in protected)


def _file_range(raw: bytes, layout: _Layout, rva: int, size: int) -> bytes:
    _require(size > 0 and rva + size <= layout.image_size)
    for section in layout.sections:
        if section.rva <= rva and rva + size <= section.rva + section.raw_size:
            offset = section.raw_offset + rva - section.rva
            return raw[offset:offset + size]
    raise MemoryObservationError(FailureReason.UNSUPPORTED)


def _relocations(raw: bytes, layout: _Layout, protected: tuple[ImageRange, ...]) -> None:
    rva, size = layout.relocations
    if not rva and not size:
        return
    _require(size <= _MAX_CHECKED)
    data = _file_range(raw, layout, rva, size)
    offset = 0
    while offset < len(data):
        _require(offset + 8 <= len(data))
        page, block_size = struct.unpack_from("<II", data, offset)
        _require(page < layout.image_size and page % 4096 == 0)
        _require(8 <= block_size <= len(data) - offset and block_size % 2 == 0)
        entries = data[offset + 8:offset + block_size]
        _relocation_entries(entries, page, layout.image_size, protected)
        offset += block_size


def _relocation_entries(data: bytes, page: int, image_size: int,
                        protected: tuple[ImageRange, ...]) -> None:
    for (entry,) in struct.iter_unpack("<H", data):
        kind, address = entry >> 12, page + (entry & 0xFFF)
        if kind == 0:
            continue
        _require(kind == 10 and address + 8 <= image_size)
        _require(not _overlaps(address, 8, protected))


def _protected_ranges(raw: bytes, layout: _Layout) -> tuple[ImageRange, ...]:
    header_digest = hashlib.sha256(raw[:layout.header_size]).hexdigest()
    ranges = [ImageRange(0, layout.header_size, header_digest)]
    executable = [item for item in layout.sections if item.flags & _EXECUTE]
    _require(bool(executable))
    _require(any(item.rva <= layout.entry < item.rva + item.virtual_size for item in executable))
    for section in executable:
        _require(bool(section.flags & _READ) and not section.flags & _WRITE)
        _require(section.size <= _MAX_CHECKED - sum(item.size for item in ranges))
        content = raw[section.raw_offset:section.raw_offset + section.raw_size]
        content += bytes(section.size - section.raw_size)
        ranges.append(ImageRange(section.rva, section.size, hashlib.sha256(content).hexdigest()))
    protected = tuple(sorted(ranges, key=lambda item: item.rva))
    return protected


def plan_pinned_image(raw: bytes, pin: PinnedExecutable) -> ImageCodePlan:
    """Cover all executable sections of a pinned x64 image; unsupported layouts fail closed."""
    _require(isinstance(raw, bytes) and 0 < len(raw) <= _MAX_FILE)
    _require(isinstance(pin, PinnedExecutable))
    _require(hmac.compare_digest(hashlib.sha256(raw).hexdigest(), pin.sha256))
    layout = _layout(raw)
    protected = _protected_ranges(raw, layout)
    _relocations(raw, layout, protected)
    rva, size = layout.imports
    if rva or size:
        _file_range(raw, layout, rva, size)
        _require(not _overlaps(rva, size, protected))
    return ImageCodePlan(pin.executable, pin.version, pin.sha256, layout.image_size, protected,
                         _token=_PLAN_TOKEN)
