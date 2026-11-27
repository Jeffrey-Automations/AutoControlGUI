"""In-memory document store for the LSP server.

LSP clients send ``textDocument/didOpen`` with the full file contents
and ``didChange`` with either full or incremental updates. The server
needs the *current* text whenever hover / completion / diagnostics is
requested — that's what this module owns. Pure stdlib, thread-safe.

LSP positions count ``character`` in UTF-16 code units, while a Python
string index counts code points: an emoji or any other character outside
the BMP is two units but one index. Every position is converted at this
boundary (:func:`utf16_to_index`); using the column as an index put the
cursor, and range edits, past the right spot on such a line.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence


@dataclass(frozen=True)
class Position:
    """Zero-based ``(line, character)`` LSP position; ``character`` is in UTF-16 units."""

    line: int
    character: int


@dataclass(frozen=True)
class TextDocument:
    """Versioned text snapshot keyed by URI."""

    uri: str
    text: str
    version: int = 0

    def lines(self) -> List[str]:
        return self.text.splitlines()

    def word_at(self, position: Position) -> str:
        """Return the identifier-like word under ``position`` (LSP style)."""
        rows = self.lines()
        if position.line < 0 or position.line >= len(rows):
            return ""
        line = rows[position.line]
        if position.character < 0 or position.character > utf16_length(line):
            return ""
        return _word_around(line, utf16_to_index(line, position.character))


class DocumentStore:
    """Thread-safe ``uri → TextDocument`` map for the LSP loop."""

    def __init__(self) -> None:
        self._docs: Dict[str, TextDocument] = {}
        self._lock = threading.RLock()

    def open(self, uri: str, text: str, version: int = 0) -> TextDocument:
        doc = TextDocument(uri=str(uri), text=str(text), version=int(version))
        with self._lock:
            self._docs[doc.uri] = doc
        return doc

    def replace(self, uri: str, text: str,
                 version: Optional[int] = None) -> TextDocument:
        with self._lock:
            existing = self._docs.get(uri)
        next_version = _resolve_next_version(version, existing)
        return self.open(uri, text, next_version)

    def close(self, uri: str) -> bool:
        with self._lock:
            return self._docs.pop(uri, None) is not None

    def get(self, uri: str) -> Optional[TextDocument]:
        with self._lock:
            return self._docs.get(uri)

    def count(self) -> int:
        with self._lock:
            return len(self._docs)

    def apply_change(self, uri: str,
                     changes: Sequence[Dict],
                     version: Optional[int] = None,
                     ) -> Optional[TextDocument]:
        """Apply LSP ``contentChanges`` entries to the stored document.

        Supports both full-document and range-incremental forms.
        Returns the updated document, or None when the URI isn't tracked.
        """
        with self._lock:
            doc = self._docs.get(uri)
        if doc is None:
            return None
        text = doc.text
        for change in changes:
            if "range" not in change:
                text = str(change.get("text", ""))
                continue
            text = _apply_range_edit(text, change["range"],
                                       str(change.get("text", "")))
        return self.replace(uri, text, version=version)


# --- helpers -------------------------------------------------

def _utf16_units(char: str) -> int:
    return 2 if ord(char) > 0xFFFF else 1


def utf16_length(line: str) -> int:
    """Length of ``line`` in UTF-16 code units, as an LSP client counts it."""
    return sum(_utf16_units(char) for char in line)


def utf16_to_index(line: str, units: int) -> int:
    """Python index of the UTF-16 column ``units`` in ``line``.

    Clamped to ``[0, len(line)]``, as LSP clamps a column past the line
    end. A column inside a surrogate pair rounds to the character after it.
    """
    count = 0
    for index, char in enumerate(line):
        if count >= units:
            return index
        count += _utf16_units(char)
    return len(line)


def _resolve_next_version(override: Optional[int],
                           existing: Optional[TextDocument]) -> int:
    """Pick the next document version: explicit override → existing+1 → 0."""
    if override is not None:
        return int(override)
    if existing is not None:
        return existing.version + 1
    return 0


_WORD_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


def _word_around(line: str, index: int) -> str:
    if index >= len(line):
        index = len(line) - 1
    if index < 0:
        return ""
    if line[index] not in _WORD_CHARS:
        # Try the character to the left — common when cursor sits after a name.
        if index > 0 and line[index - 1] in _WORD_CHARS:
            index -= 1
        else:
            return ""
    start = index
    while start > 0 and line[start - 1] in _WORD_CHARS:
        start -= 1
    end = index
    while end + 1 < len(line) and line[end + 1] in _WORD_CHARS:
        end += 1
    return line[start:end + 1]


def _apply_range_edit(text: str, lsp_range: Dict,
                       new_text: str) -> str:
    start = lsp_range.get("start") or {}
    end = lsp_range.get("end") or {}
    start_index = _offset_for(text, int(start.get("line", 0)),
                              int(start.get("character", 0)))
    end_index = _offset_for(text, int(end.get("line", 0)),
                            int(end.get("character", 0)))
    if start_index > end_index:
        start_index, end_index = end_index, start_index
    return text[:start_index] + new_text + text[end_index:]


def _offset_for(text: str, line: int, char: int) -> int:
    """Index in ``text`` of the LSP position ``(line, char)``.

    A line past the end gives ``len(text)``; a column past the end of its
    line stops at that line's end rather than running into the next one.
    """
    start = 0
    for _ in range(max(0, line)):
        newline = text.find("\n", start)
        if newline < 0:
            return len(text)
        start = newline + 1
    end = text.find("\n", start)
    row = text[start:] if end < 0 else text[start:end]
    if row.endswith("\r"):
        row = row[:-1]
    return start + utf16_to_index(row, char)


__all__ = [
    "DocumentStore", "Position", "TextDocument", "utf16_length",
    "utf16_to_index",
]
