"""Screenshot panel lifecycle and state with every native operation replaced."""
import os
import threading
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QEvent, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from shiboken6 import isValid  # noqa: E402
from headless._qt_settle import pump_until  # noqa: E402
from je_auto_control.gui import _screenshot_tab as module  # noqa: E402
from je_auto_control.gui.tab_registry import TAB_SPECS, TabEntry, TabRegistry, lazy_factory  # noqa: E402


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    calls = SimpleNamespace(captures=[], pixels=[], dialogs=[], warnings=[], sizes=[], selections=[])
    monkeypatch.setattr(module, "screen_size", lambda: (calls.sizes.append(True) or (800, 600)))
    monkeypatch.setattr(module, "screenshot", lambda **kw: calls.captures.append(kw))
    monkeypatch.setattr(module, "get_pixel", lambda x, y: (calls.pixels.append((x, y)) or (1, 2, 3)))
    monkeypatch.setattr(module, "open_region_selector",
                        lambda parent: (calls.selections.append(True) or (10, 20, 30, 40)))
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName",
                        lambda *args: (calls.dialogs.append(True) or ("chosen.png", "PNG")))
    return calls


def _delete(app, widget):
    widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def test_screenshot_tab_is_lazy_and_close_rebuilds_owned_state(app, fakes):
    spec = next(spec for spec in TAB_SPECS if spec.key == "screenshot")
    owner = QWidget()
    entry = TabEntry(spec.key, spec.title_key, lazy_factory(spec.module, spec.class_name),
                     on_build=lambda page: page.setParent(owner))
    registry = TabRegistry([entry])
    assert not entry.built
    page = registry.open("screenshot")
    assert not any(vars(fakes).values()), "construction performed native or dialog work"
    page.ss_path_input.setText("old.png")
    page.ss_result_text.setText("old result")
    page.hide()
    assert registry.open("screenshot") is page
    assert page.ss_path_input.text() == "old.png"
    registry.close("screenshot")
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert not isValid(page)
    assert not entry.built
    replacement = registry.open("screenshot")
    assert replacement is not page
    assert replacement.ss_path_input.text() == ""
    assert replacement.ss_result_text.toPlainText() == ""
    assert not hasattr(owner, "ss_path_input")
    _delete(app, owner)


def test_screenshot_actions_preserve_picker_region_convention(app, fakes):
    page = module.ScreenshotTab()
    try:
        actions = dict(page.menu_actions())
        assert list(actions) == ["take_screenshot", "browse", "pick_region", "get_screen_size", "get_pixel_label"]
        actions["browse"]()
        assert page.ss_path_input.text() == "chosen.png"
        actions["pick_region"]()
        assert page.ss_region_input.text() == "10, 20, 40, 60"
        actions["take_screenshot"]()
        assert pump_until(lambda: not page._task.running)
        assert fakes.captures == [{"file_path": "chosen.png", "screen_region": [10, 20, 40, 60]}]
        assert "chosen.png" in page.ss_result_text.toPlainText()
        actions["get_screen_size"]()
        assert pump_until(lambda: not page._task.running)
        assert page.screen_size_label.text() == "800 x 600"
        page.pixel_x_input.setText("7")
        page.pixel_y_input.setText("8")
        actions["get_pixel_label"]()
        assert pump_until(lambda: not page._task.running)
        assert fakes.pixels == [(7, 8)]
        assert "(1, 2, 3)" in page.pixel_result_label.text()
    finally:
        _delete(app, page)


def test_pixel_error_survives_retranslation_after_success(app, monkeypatch):
    page = module.ScreenshotTab()
    try:
        page._get_pixel_color()
        assert pump_until(lambda: not page._task.running)
        assert "(1, 2, 3)" in page.pixel_result_label.text()

        def fail(x, y):
            raise RuntimeError("pixel unavailable")

        monkeypatch.setattr(module, "get_pixel", fail)
        page._get_pixel_color()
        assert pump_until(lambda: not page._task.running)
        page.retranslate()
        assert page.pixel_result_label.text() == "Error: pixel unavailable"
        monkeypatch.setattr(module, "get_pixel", lambda x, y: (4, 5, 6))
        page._get_pixel_color()
        assert pump_until(lambda: not page._task.running)
        page.retranslate()
        assert "(4, 5, 6)" in page.pixel_result_label.text()
        assert "Error" not in page.pixel_result_label.text()
    finally:
        _delete(app, page)


def test_invalid_inputs_do_not_call_native_backends(app, fakes):
    page = module.ScreenshotTab()
    try:
        page.ss_region_input.setText("invalid")
        page._take_screenshot()
        assert page.ss_result_text.toPlainText().startswith("Error")
        page.pixel_x_input.setText("invalid")
        page._get_pixel_color()
        assert pump_until(lambda: not page._task.running)
        assert page.pixel_result_label.text().startswith("Error")
        assert fakes.captures == [] and fakes.pixels == []
    finally:
        _delete(app, page)


def test_cancelled_dialogs_keep_current_inputs(app, monkeypatch):
    monkeypatch.setattr(module, "open_region_selector", lambda parent: None)
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    page = module.ScreenshotTab()
    try:
        page.ss_path_input.setText("keep.png")
        page.ss_region_input.setText("1, 2, 3, 4")
        page._browse_ss_path()
        page._pick_ss_region()
        assert page.ss_path_input.text() == "keep.png"
        assert page.ss_region_input.text() == "1, 2, 3, 4"
    finally:
        _delete(app, page)

@pytest.mark.parametrize("operation,backend", [
    ("_get_screen_size", "screen_size"),
    ("_take_screenshot", "screenshot"),
    ("_get_pixel_color", "get_pixel"),
])
def test_capture_operations_run_off_gui_thread(app, monkeypatch, operation, backend):
    threads = []

    def call(*args, **kwargs):
        threads.append(threading.get_ident())
        return (800, 600) if backend == "screen_size" else (1, 2, 3)

    monkeypatch.setattr(module, backend, call)
    page = module.ScreenshotTab()
    try:
        getattr(page, operation)()
        assert pump_until(lambda: not page._task.running)
        assert len(threads) == 1 and threads[0] != threading.get_ident()
    finally:
        _delete(app, page)


@pytest.mark.parametrize("fail", [False, True])
def test_capture_close_reopen_discards_late_outcome(app, monkeypatch, fail):
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    calls, ticks = [], []

    def capture(**kwargs):
        calls.append(kwargs)
        entered.set()
        try:
            assert release.wait(5), "test did not release fake capture"
            if fail:
                raise RuntimeError("late capture error")
        finally:
            exited.set()

    monkeypatch.setattr(module, "screenshot", capture)
    monkeypatch.setattr(module.language_wrapper, "translate",
                        lambda key, fallback: "localized running" if key == "task_running" else fallback)
    owner = QWidget()
    entry = TabEntry("screenshot", "tab_screenshot", module.ScreenshotTab,
                     on_build=lambda page: page.setParent(owner))
    registry = TabRegistry([entry])
    page = registry.open("screenshot")
    timer = QTimer(owner)
    timer.setInterval(1)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start()
    try:
        page.ss_path_input.setText("original.png")
        page.ss_region_input.setText("1, 2, 3, 4")
        page._take_screenshot()
        assert page.ss_result_text.toPlainText() == "localized running"
        page.ss_result_text.setText("retained status")
        page.ss_path_input.setText("changed.png")
        page.ss_region_input.setText("invalid")
        page._take_screenshot()
        assert page.ss_result_text.toPlainText() == "retained status"
        assert pump_until(lambda: entered.is_set() and bool(ticks))
        assert calls == [{"file_path": "original.png", "screen_region": [1, 2, 3, 4]}]
        registry.close("screenshot")
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        assert not isValid(page)
        replacement = registry.open("screenshot")
        release.set()
        assert pump_until(exited.is_set)
        assert replacement.ss_result_text.toPlainText() == ""
    finally:
        release.set()
        assert pump_until(exited.is_set)
        _delete(app, owner)


def test_size_failure_is_displayed_inline(app, monkeypatch):
    def fail():
        raise RuntimeError("size unavailable")

    monkeypatch.setattr(module, "screen_size", fail)
    page = module.ScreenshotTab()
    try:
        page._get_screen_size()
        assert pump_until(lambda: not page._task.running)
        assert page.screen_size_label.text() == "Error: size unavailable"
    finally:
        _delete(app, page)
