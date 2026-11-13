"""Remote Desktop's collapsible sections: a bare title bar when closed, one title when a group is wrapped."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    return widgets.QApplication.instance() or widgets.QApplication([])


def _themed(qapp, *sections):
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from je_auto_control.gui.theme import DARK, apply_theme
    window = QWidget()
    layout = QVBoxLayout(window)
    for section in sections:
        layout.addWidget(section)
    layout.addStretch(1)
    apply_theme(window, DARK)
    window.resize(400, 400)
    window.show()
    qapp.processEvents()
    return window


def test_a_closed_section_is_only_as_tall_as_its_title_padding(qapp):
    from PySide6.QtWidgets import QCheckBox, QVBoxLayout
    from je_auto_control.gui.remote_desktop._helpers import _CollapsibleSection
    section = _CollapsibleSection("Advanced")
    body = QVBoxLayout()
    body.addWidget(QCheckBox("Enable audio"))
    section.set_body_layout(body)
    window = _themed(qapp, section)
    try:
        margins = section.contentsMargins()
        assert section.height() == margins.top() + margins.bottom(), "no strip under the title"
        assert section.property("collapsed") is True
        section.setChecked(True)
        qapp.processEvents()
        assert section.body.isVisible() and section.property("collapsed") is False
        assert section.height() > margins.top() + margins.bottom() + section.body.sizeHint().height() - 1
    finally:
        window.hide()
        window.deleteLater()


def test_an_adopted_group_gives_up_its_title_and_frame(qapp):
    from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout
    from je_auto_control.gui.remote_desktop._helpers import _CollapsibleSection
    section = _CollapsibleSection("Folder sync")
    inner = QGroupBox("Folder sync")
    QVBoxLayout(inner).addWidget(QLabel("Local folder"))
    section.adopt(inner)
    window = _themed(qapp, section)
    try:
        assert inner.title() == ""
        assert inner.parent() is section.body
        assert "border: none" in inner.styleSheet()
    finally:
        window.hide()
        window.deleteLater()


def test_a_language_switch_does_not_give_the_wrapped_group_its_title_back(qapp):
    pytest.importorskip("aiortc", exc_type=ImportError)
    from PySide6.QtWidgets import QGroupBox, QWidget
    from je_auto_control.gui._i18n_helpers import TranslatableMixin
    from je_auto_control.gui.remote_desktop.webrtc_viewer_ui import _ViewerUiMixin

    class Host(TranslatableMixin, QWidget):
        _wrap_collapsed = _ViewerUiMixin._wrap_collapsed

    host = Host()
    inner = host._tr(QGroupBox(), "rd_webrtc_sync_group")
    section = host._wrap_collapsed(inner, "rd_webrtc_sync_group")
    host.retranslate()
    assert inner.title() == "" and section.title() != ""
    host.deleteLater()
