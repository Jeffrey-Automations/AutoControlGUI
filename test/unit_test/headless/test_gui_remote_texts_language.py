"""Remote Desktop texts set from state follow a language switch (offscreen Qt; no session, no tray shown)."""
import os

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QSystemTrayIcon  # noqa: E402

from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture()
def english():
    previous = language_wrapper.language
    language_wrapper.reset_language("English")
    yield
    language_wrapper.reset_language(previous)


def _in_language(key, **fields):
    text = language_wrapper.translate(key, key)
    for name, value in fields.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def _dispose(qapp, widget):
    getattr(widget, "dispose", widget.close)()
    widget.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def test_the_legacy_viewer_status_and_progress_follow_a_switch(qapp, english):
    from je_auto_control.gui.remote_desktop.viewer_panel import _ViewerPanel
    panel = _ViewerPanel()
    try:
        panel._on_displaced("viewer", "script")
        panel._on_file_complete_main("t1", False, "disk full", "")
        before = (panel._status.text(), panel._progress_label.text())
        assert before == (_in_language("rd_viewer_displaced"), _in_language("rd_progress_failed", error="disk full"))
        language_wrapper.reset_language("Japanese")
        panel.retranslate()
        after = (panel._status.text(), panel._progress_label.text())
        assert after == (_in_language("rd_viewer_displaced"), _in_language("rd_progress_failed", error="disk full"))
        assert after[0] != before[0] and after[1] != before[1]
    finally:
        _dispose(qapp, panel)


def test_the_viewer_screen_window_title_follows_a_switch(qapp, english):
    from je_auto_control.gui.remote_desktop.viewer_screen_window import ViewerScreenWindow
    window = ViewerScreenWindow()
    try:
        english_title = window.windowTitle()
        language_wrapper.reset_language("Japanese")
        window.retranslate()
        assert window.windowTitle() == _in_language("rd_webrtc_viewer_screen_title") != english_title
        assert not window.isVisible()
    finally:
        _dispose(qapp, window)


def test_the_tray_tip_and_menu_follow_a_switch(qapp, english, monkeypatch):
    from je_auto_control.gui.remote_desktop import tray_icon
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda self: None)     # nothing reaches the real tray
    tray = tray_icon.HostTrayIcon()
    try:
        tray.set_state(sessions=2)
        language_wrapper.reset_language("Japanese")
        tray.retranslate()
        assert tray._tray.toolTip() == _in_language("rd_webrtc_tray_running", n=2)
        assert [action.text() for action, _key in tray._actions] == [
            _in_language(key) for key in ("rd_webrtc_tray_open", "rd_webrtc_tray_stop", "rd_webrtc_tray_quit")]
        tray.set_state(sessions=0)
        assert tray._tray.toolTip() == _in_language("rd_webrtc_tray_idle")
    finally:
        tray._tray.hide()
        tray.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def test_the_missing_extras_notice_follows_a_switch(qapp, english, monkeypatch):
    from je_auto_control.gui.remote_desktop import tab as tab_module
    monkeypatch.setattr(tab_module, "_load_webrtc_panels", lambda: (None, None))
    tab = tab_module.RemoteDesktopTab()
    try:
        texts = [label.text() for label in tab.findChildren(QLabel)]
        english_notice = _in_language("rd_webrtc_missing_extras")
        assert english_notice in texts
        language_wrapper.reset_language("Japanese")
        tab.retranslate()
        texts = [label.text() for label in tab.findChildren(QLabel)]
        assert _in_language("rd_webrtc_missing_extras") in texts
        assert english_notice not in texts
    finally:
        _dispose(qapp, tab)
