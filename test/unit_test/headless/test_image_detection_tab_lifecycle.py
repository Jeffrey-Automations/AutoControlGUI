"""Owned image-detection tasks with fake capture, dialogs and desktop input."""
import os
import threading
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QEvent, QTimer  # noqa: E402  # reason: optional Qt
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402  # reason: optional Qt
from shiboken6 import isValid  # noqa: E402  # reason: optional Qt
from headless._qt_settle import pump_until  # noqa: E402  # reason: optional Qt
from je_auto_control.gui import _image_detect_tab as module  # noqa: E402  # reason: optional Qt
from je_auto_control.gui.tab_registry import (  # noqa: E402  # reason: optional Qt
    TAB_SPECS, TabEntry, TabRegistry, lazy_factory,
)
from je_auto_control.wrapper import auto_control_image as backend  # noqa: E402  # reason: optional Qt


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    calls = SimpleNamespace(center=[], all=[], click=[], crop=[], dialogs=[], warnings=[])
    monkeypatch.setattr(module, "locate_image_center", lambda *args: (calls.center.append(args) or (3, 4)))
    monkeypatch.setattr(module, "locate_all_image", lambda *args: (calls.all.append(args) or [[1, 2, 5, 6]]))
    monkeypatch.setattr(module, "locate_and_click", lambda *args: (calls.click.append(args) or (3, 4)))
    monkeypatch.setattr(module, "crop_template_to_file", lambda *args: (calls.crop.append(args) or (1, 2, 3, 4)))
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName",
                        lambda *args: (calls.dialogs.append(True) or ("chosen.png", "PNG")))
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName",
                        lambda *args: (calls.dialogs.append(True) or ("crop.png", "PNG")))
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *args: calls.warnings.append(args))
    return calls


def _delete(app, widget):
    widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def test_lazy_panel_owns_controls_and_rebuilds_after_close(app, fakes):
    spec = next(spec for spec in TAB_SPECS if spec.key == "image_detect")
    owner = QWidget()
    entry = TabEntry(spec.key, spec.title_key, lazy_factory(spec.module, spec.class_name),
                     on_build=lambda page: page.setParent(owner))
    registry = TabRegistry([entry])
    assert not entry.built
    page = registry.open("image_detect")
    assert not any(vars(fakes).values())
    page.img_path_input.setText("old.png")
    page.mouse_button_combo.setCurrentText("mouse_right")
    page.hide()
    assert registry.open("image_detect") is page
    assert not hasattr(owner, "img_path_input")
    registry.close("image_detect")
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert not isValid(page) and not entry.built
    replacement = registry.open("image_detect")
    assert replacement.img_path_input.text() == ""
    assert replacement.mouse_button_combo.currentText() == "mouse_left"
    assert replacement.detect_result_text.toPlainText() == ""
    _delete(app, owner)


def test_actions_keep_detection_and_click_separate_with_local_button(app, fakes):
    page = module.ImageDetectionTab()
    try:
        actions = dict(page.menu_actions())
        assert list(actions) == ["browse", "crop_template", "locate_image", "locate_all", "locate_click", "task_stop"]
        actions["browse"]()
        assert page.img_path_input.text() == "chosen.png"
        actions["crop_template"]()
        assert page.img_path_input.text() == "crop.png"
        page.threshold_input.setText("0.65")
        page.draw_check.setChecked(True)
        page.mouse_button_combo.setCurrentText("mouse_right")
        actions["locate_image"]()
        assert pump_until(lambda: not page._task.running)
        assert fakes.center == [("crop.png", 0.65, True)] and fakes.click == []
        actions["locate_all"]()
        assert pump_until(lambda: not page._task.running)
        assert fakes.all == [("crop.png", 0.65, True)] and fakes.click == []
        assert "Found 1 matches" in page.detect_result_text.toPlainText()
        actions["locate_click"]()
        assert pump_until(lambda: not page._task.running)
        assert fakes.click == [("crop.png", "mouse_right", 0.65, True)]
        assert "Clicked at: (3, 4)" == page.detect_result_text.toPlainText()
    finally:
        _delete(app, page)


@pytest.mark.parametrize("threshold", ["nan", "inf", "-0.1", "1.1", "bad"])
def test_invalid_threshold_is_rejected_without_backend_call(app, fakes, threshold):
    page = module.ImageDetectionTab()
    try:
        page.img_path_input.setText("template.png")
        page.threshold_input.setText(threshold)
        page._locate_click()
        assert page.detect_result_text.toPlainText().startswith("Error:")
        assert fakes.click == [] and not page._task.running
    finally:
        _delete(app, page)


def test_dialog_cancellation_and_retranslation_preserve_state(app, fakes, monkeypatch):
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    page = module.ImageDetectionTab()
    try:
        page.img_path_input.setText("keep.png")
        page._browse_img()
        page._crop_template()
        assert page.img_path_input.text() == "keep.png" and fakes.crop == []
        page._on_error(RuntimeError("keep error"))
        page.retranslate()
        assert page.detect_result_text.toPlainText() == "Error: keep error"
    finally:
        _delete(app, page)


@pytest.mark.parametrize("fail", [False, True])
def test_worker_snapshots_inputs_keeps_ui_live_and_discards_after_close(app, monkeypatch, fail):
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    calls, ticks = [], []

    def detect(*args):
        calls.append((args, threading.get_ident()))
        entered.set()
        try:
            assert release.wait(5)
            if fail:
                raise RuntimeError("late detection error")
            return (3, 4)
        finally:
            exited.set()

    monkeypatch.setattr(module, "locate_image_center", detect)
    monkeypatch.setattr(module.language_wrapper, "translate", lambda key, fallback: "running" if key == "task_running"
                        else fallback)
    owner = QWidget()
    entry = TabEntry("image_detect", "tab_image_detect", module.ImageDetectionTab,
                     on_build=lambda page: page.setParent(owner))
    registry = TabRegistry([entry])
    page = registry.open("image_detect")
    timer = QTimer(owner)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(1)
    try:
        page.img_path_input.setText("original.png")
        page._locate_image()
        assert page.detect_result_text.toPlainText() == "running"
        page.img_path_input.setText("changed.png")
        page.threshold_input.setText("bad")
        page._locate_click()
        assert pump_until(lambda: entered.is_set() and bool(ticks))
        assert calls == [(("original.png", 0.8, False), calls[0][1])]
        assert calls[0][1] != threading.get_ident()
        registry.close("image_detect")
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        assert not isValid(page)
        replacement = registry.open("image_detect")
        release.set()
        assert pump_until(exited.is_set)
        assert replacement.detect_result_text.toPlainText() == ""
    finally:
        release.set()
        assert pump_until(exited.is_set)
        _delete(app, owner)


@pytest.mark.parametrize("close", [False, True])
def test_cancel_during_detection_prevents_late_mouse_input(app, monkeypatch, close):
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    inputs = []

    def find(*args):
        entered.set()
        assert release.wait(5)
        return [True, [1, 2, 5, 6]]

    def locate(*args):
        try:
            return backend.locate_and_click(*args)
        finally:
            exited.set()

    monkeypatch.setattr(backend.template_detection, "find_image", find)
    monkeypatch.setattr(backend, "set_mouse_position", lambda *args: inputs.append(args))
    monkeypatch.setattr(backend, "click_mouse", lambda *args: inputs.append(args))
    monkeypatch.setattr(module, "locate_and_click", locate)
    page = module.ImageDetectionTab()
    try:
        page.img_path_input.setText("template.png")
        page._locate_click()
        assert pump_until(entered.is_set)
        if close:
            page.dispose()
            _delete(app, page)
        else:
            page._stop()
        release.set()
        assert pump_until(exited.is_set)
        assert inputs == []
        if not close:
            assert pump_until(lambda: not page._task.running)
            assert page.detect_result_text.toPlainText() == module._t("task_stopped")
    finally:
        release.set()
        assert pump_until(exited.is_set)
        if isValid(page):
            _delete(app, page)
