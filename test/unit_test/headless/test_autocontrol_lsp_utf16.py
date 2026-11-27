"""LSP columns are UTF-16 code units; the document store converts them.

An LSP client counts ``character`` in UTF-16 units, so a character outside
the BMP (an emoji) is two units but one Python index. Using the column as
an index moved the cursor right by one per emoji before it: hover found no
word, and an incremental edit landed in the wrong place.
"""
import sys
from pathlib import Path

import pytest

_LSP_DIR = Path(__file__).resolve().parents[3] / "autocontrol-lsp"
if str(_LSP_DIR) not in sys.path:
    sys.path.insert(0, str(_LSP_DIR))

_EMOJI = "\U0001F600"
# Ten emoji before the command: ten units further right than the indices.
_LINE = '["' + _EMOJI * 10 + '", ["AC_sleep", {"seconds": 1}]]'


def _units(text: str) -> int:
    """What an LSP client reports as the column after ``text``."""
    return len(text.encode("utf-16-le")) // 2


def _column_of(line: str, needle: str, offset: int = 0) -> int:
    return _units(line[:line.index(needle) + offset])


def test_utf16_to_index_counts_surrogate_pairs():
    from autocontrol_lsp.server.documents import utf16_length, utf16_to_index
    line = "a" + _EMOJI + "b"
    assert utf16_length(line) == 4
    assert [utf16_to_index(line, units) for units in range(5)] == [0, 1, 2, 2, 3]
    assert utf16_to_index(line, 99) == len(line)
    assert utf16_to_index(line, -1) == 0


@pytest.mark.parametrize("offset", [0, 1, 7])
def test_word_at_uses_the_clients_utf16_column(offset):
    from autocontrol_lsp.server.documents import Position, TextDocument
    doc = TextDocument("file:///x.ac.json", "[\n" + _LINE + "\n]")
    column = _column_of(_LINE, "AC_sleep", offset)
    assert doc.word_at(Position(line=1, character=column)) == "AC_sleep"


def test_word_at_rejects_a_column_past_the_utf16_line_end():
    from autocontrol_lsp.server.documents import Position, TextDocument
    doc = TextDocument("u", _LINE)
    assert doc.word_at(Position(line=0, character=_units(_LINE) + 1)) == ""


def test_hover_on_a_line_with_emoji_before_the_command():
    from autocontrol_lsp.server.documents import DocumentStore
    from autocontrol_lsp.server.handlers import handle_hover
    store = DocumentStore()
    store.open("file:///x.ac.json", _LINE)
    reply = handle_hover({
        "textDocument": {"uri": "file:///x.ac.json"},
        "position": {"line": 0, "character": _column_of(_LINE, "AC_sleep", 3)},
    }, store)
    assert reply
    assert reply["contents"]["kind"] == "plaintext"


def _range_edit(text: str, start, end, new_text: str) -> str:
    from autocontrol_lsp.server.documents import DocumentStore
    store = DocumentStore()
    store.open("u", text)
    updated = store.apply_change("u", [{
        "range": {"start": {"line": start[0], "character": start[1]},
                  "end": {"line": end[0], "character": end[1]}},
        "text": new_text,
    }])
    return updated.text


def test_range_edit_after_emoji_replaces_the_intended_text():
    line = '["' + _EMOJI * 3 + '", ["AC_slep"]]'
    start = _column_of(line, "AC_slep")
    end = start + len("AC_slep")
    text = "[\n" + line + "\n]"
    assert _range_edit(text, (1, start), (1, end), "AC_sleep") == (
        "[\n" + line.replace("AC_slep", "AC_sleep") + "\n]")


def test_range_edit_spanning_lines_with_emoji_on_both():
    first = _EMOJI + "ab"
    second = _EMOJI * 2 + "cd"
    text = first + "\r\n" + second
    edited = _range_edit(text, (0, _units(_EMOJI + "a")), (1, _units(_EMOJI * 2 + "c")), "-")
    assert edited == _EMOJI + "a-d"


def test_range_edit_column_past_line_end_stops_at_that_line():
    """LSP clamps a column to the line length; it must not eat the newline."""
    assert _range_edit("ab\ncd", (0, 1), (0, 50), "X") == "aX\ncd"
