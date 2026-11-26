"""The script editors read and write their files off the GUI thread.

The Flow Editor, the Script Builder and the Recording Editor opened, saved and
exported inside the slot; a recording can be several megabytes. Offscreen Qt
against gated fakes: the slot returns first, the tab says it is running or
busy, the outcome arrives later on the GUI thread, and disposing the tab drops
one still out. Every file dialog is faked.
"""
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox  # noqa: E402

from headless._qt_settle import pump_until  # noqa: E402
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402

_WAIT = 10.0


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


class _Gate:
    """A backend call that blocks until released, remembers where it ran, then delegates."""

    def __init__(self, then) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.threads: list = []
        self.then = then

    def __call__(self, *args, **kwargs):
        self.threads.append(threading.get_ident())
        self.entered.set()
        self.release.wait(_WAIT)
        return self.then(*args, **kwargs)

    def off_gui_thread(self) -> bool:
        return bool(self.threads) and all(ident != threading.get_ident() for ident in self.threads)


@pytest.fixture
def boxes(monkeypatch):
    QApplication.instance() or QApplication([])
    shown = []
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, lambda *args: shown.append(args[-1]))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: ("", ""))
    return shown


def _returns_at_once(slot) -> None:
    started = time.monotonic()
    slot()
    assert time.monotonic() - started < 5.0, "the slot held the GUI thread"


def _paths(monkeypatch, source, target) -> None:
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(source), ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))


def _script(tmp_path):
    source = tmp_path / "in.json"
    source.write_text('[["AC_click_mouse", {"mouse_keycode": "mouse_left"}]]', encoding="utf-8")
    return source, tmp_path / "out.json"


def _round_trip(tab, tasks, status, open_slot, save_slot, gate_load, gate_save) -> None:
    _returns_at_once(open_slot)
    assert gate_load.entered.wait(_WAIT)
    assert status() == _t("task_running")
    open_slot()                                     # one file at a time
    assert status() == _t("task_busy")
    gate_load.release.set()
    assert pump_until(lambda: not tasks.running)
    _returns_at_once(save_slot)
    assert gate_save.entered.wait(_WAIT)
    gate_save.release.set()
    assert pump_until(lambda: not tasks.running)
    assert gate_load.off_gui_thread() and gate_save.off_gui_thread()


def test_the_flow_editor_opens_and_saves_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui.flow_editor import tab as module
    source, target = _script(tmp_path)
    _paths(monkeypatch, source, target)
    load, save = _Gate(module.load_action_file), _Gate(module.save_action_file)
    monkeypatch.setattr(module, "load_action_file", load)
    monkeypatch.setattr(module, "save_action_file", save)
    tab = module.FlowEditorTab()
    _round_trip(tab, tab._files, tab._status.text, tab._on_open, tab._on_save, load, save)
    assert len(tab.steps()) == 1 and target.exists() and boxes == []
    tab.dispose()
    tab.deleteLater()


def test_the_script_builder_loads_and_saves_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui.script_builder import builder_tab as module
    source, target = _script(tmp_path)
    _paths(monkeypatch, source, target)
    load, save = _Gate(module.load_action_file), _Gate(module.save_action_file)
    monkeypatch.setattr(module, "load_action_file", load)
    monkeypatch.setattr(module, "save_action_file", save)
    tab = module.ScriptBuilderTab()
    _round_trip(tab, tab._files, tab._result.toPlainText, tab._on_load, tab._on_save, load, save)
    assert len(tab._tree.root_steps()) == 1 and target.exists() and boxes == []
    tab.dispose()
    tab.deleteLater()


def test_the_recording_editor_loads_saves_and_exports_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui import recording_editor_tab as module
    source, target = _script(tmp_path)
    _paths(monkeypatch, source, target)
    load, save = _Gate(module.read_action_json), _Gate(module.write_action_json)
    monkeypatch.setattr(module, "read_action_json", load)
    monkeypatch.setattr(module, "write_action_json", save)
    tab = module.RecordingEditorTab()
    tab._path_input.setText(str(source))
    _round_trip(tab, tab._files, tab._status.text, tab._load, tab._save_as, load, save)
    assert tab._status.text() == f"Saved to {target}" and target.exists()
    export = _Gate(module.generate_code_file)
    monkeypatch.setattr(module, "generate_code_file", export)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: ("python", True))
    code = tmp_path / "out.py"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(code), ""))
    _returns_at_once(tab._export_code)
    assert export.entered.wait(_WAIT)
    export.release.set()
    assert pump_until(lambda: not tab._files.running)
    assert export.off_gui_thread() and code.exists() and boxes == []
    tab.dispose()
    tab.deleteLater()


def test_disposing_the_recording_editor_drops_a_load_still_out(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui import recording_editor_tab as module
    source, _target = _script(tmp_path)
    load = _Gate(module.read_action_json)
    monkeypatch.setattr(module, "read_action_json", load)
    tab = module.RecordingEditorTab()
    tab._path_input.setText(str(source))
    tab._load()
    assert load.entered.wait(_WAIT)
    tab.dispose()
    load.release.set()
    pump_until(lambda: False, timeout=0.5)
    assert tab._list.count() == 0
    tab.deleteLater()
