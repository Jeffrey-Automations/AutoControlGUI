"""GUI test: recording editor Undo (Ctrl+Z) restores after edits."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication  # noqa: E402

from je_auto_control.gui.recording_editor_tab import (  # noqa: E402
    RecordingEditorTab,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _names(tab):
    return [action[0] for action in tab._actions]


def test_remove_then_undo_restores(qapp):
    tab = RecordingEditorTab()
    tab._actions = [["AC_a"], ["AC_b"], ["AC_c"]]
    tab._refresh()
    tab._list.setCurrentRow(1)
    tab._remove_selected()
    assert _names(tab) == ["AC_a", "AC_c"]
    tab._undo()
    assert _names(tab) == ["AC_a", "AC_b", "AC_c"]


def test_undo_with_empty_stack_is_a_noop(qapp):
    tab = RecordingEditorTab()
    tab._actions = [["AC_x"]]
    tab._refresh()
    tab._undo()  # nothing recorded yet
    assert _names(tab) == ["AC_x"]


def test_undo_unwinds_multiple_edits(qapp):
    tab = RecordingEditorTab()
    tab._actions = [["AC_a"], ["AC_b"]]
    tab._refresh()
    tab._list.setCurrentRow(0)
    tab._remove_selected()                  # -> [AC_b]
    tab._mutate([["AC_b"], ["AC_c"]])       # -> [AC_b, AC_c]
    assert _names(tab) == ["AC_b", "AC_c"]
    tab._undo()                             # back to [AC_b]
    assert _names(tab) == ["AC_b"]
    tab._undo()                             # back to [AC_a, AC_b]
    assert _names(tab) == ["AC_a", "AC_b"]


@pytest.mark.parametrize("content", ["{\"a\": 1}", "[[]]", "[1]", "5"])
def test_a_file_that_is_not_an_action_list_is_refused_and_the_recording_kept(qapp, monkeypatch, tmp_path, content):
    from je_auto_control.gui import recording_editor_tab as module
    warned = []
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *args: warned.append(args[-1]))
    path = tmp_path / "recording.json"
    path.write_text(content, encoding="utf-8")
    tab = RecordingEditorTab()
    tab._actions = [["AC_x"]]
    tab._path_input.setText(str(path))
    tab._load()
    from headless._qt_settle import settle
    assert settle(tab._files, "task")               # read off the GUI thread
    assert len(warned) == 1
    assert _names(tab) == ["AC_x"]
    tab.deleteLater()


@pytest.mark.parametrize("factor", ["inf", "nan"])
@pytest.mark.parametrize("field, command", [("_scale_x", "_apply_scale"), ("_scale_y", "_apply_scale"),
                                            ("_delay_factor", "_apply_delays")])
def test_a_factor_that_is_not_finite_is_refused(qapp, monkeypatch, factor, field, command):
    from je_auto_control.gui import recording_editor_tab as module
    warned = []
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *args: warned.append(args[-1]))
    tab = RecordingEditorTab()
    tab._actions = [["AC_click_mouse", {"x": 1, "y": 2}], ["AC_sleep", {"seconds": 1.0}]]
    getattr(tab, field).setText(factor)
    getattr(tab, command)()
    assert len(warned) == 1
    assert tab._actions[0][1] == {"x": 1, "y": 2} and tab._actions[1][1] == {"seconds": 1.0}
    tab.deleteLater()
