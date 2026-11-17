"""Drop-down and spin box chevrons drawn for the style sheet, and the spin box text inset."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_a_chevron_is_drawn_once_at_three_scales_in_the_given_colour(qapp, tmp_path):
    from PySide6.QtGui import QImage
    from je_auto_control.gui._arrow_icons import arrow_file
    path = arrow_file("chevron_down", "#9AA1AE", tmp_path)
    assert path is not None and path.is_file()
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        path.name, f"{path.stem}@2x.png", f"{path.stem}@3x.png"]
    image = QImage(str(path.with_name(f"{path.stem}@3x.png")))
    inked = {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())
             if image.pixelColor(x, y).alpha() == 255}
    assert inked == {"#9aa1ae"}, "the stroke is the theme colour, nothing else"
    stamp = path.stat().st_mtime_ns
    assert arrow_file("chevron_down", "#9aa1ae", tmp_path) == path and path.stat().st_mtime_ns == stamp


def test_rules_place_both_controls_and_point_at_the_drawn_files(qapp, tmp_path):
    from je_auto_control.gui._arrow_icons import arrow_rules
    from je_auto_control.gui.theme import DARK
    rules = arrow_rules(DARK, tmp_path)
    for selector in ("QComboBox::drop-down", "QComboBox::down-arrow", "QAbstractSpinBox::up-button",
                     "QAbstractSpinBox::up-arrow", "QAbstractSpinBox::down-arrow:disabled"):
        assert selector in rules
    assert rules.count(tmp_path.as_posix()) == 6, "combo: arrow and dimmed; spin: up, down and both dimmed"


def test_without_a_writable_cache_the_controls_keep_the_style_arrows(qapp, tmp_path):
    from je_auto_control.gui._arrow_icons import arrow_rules
    from je_auto_control.gui.theme import DARK
    blocker = tmp_path / "file"
    blocker.write_text("not a directory", encoding="utf-8")
    assert arrow_rules(DARK, blocker / "cache") == "", "placing the drop-down without an image would hide its arrow"


def test_the_theme_carries_the_arrow_rules(qapp):
    from PySide6.QtWidgets import QWidget
    from je_auto_control.gui.theme import LIGHT, apply_theme
    window = QWidget()
    try:
        assert "QComboBox::down-arrow" in apply_theme(window, LIGHT)
    finally:
        window.deleteLater()


def test_a_themed_spin_box_insets_its_text_like_other_fields(qapp):
    from PySide6.QtWidgets import QLineEdit, QSpinBox, QVBoxLayout, QWidget
    from je_auto_control.gui.adaptive.style import SPIN_TEXT_INSET, AdaptiveStyle
    from je_auto_control.gui.theme import DARK, apply_theme
    previous = qapp.style().name()
    style = AdaptiveStyle()
    qapp.setStyle(style)
    window = QWidget()
    try:
        spin = QSpinBox()
        QVBoxLayout(window).addWidget(spin)
        apply_theme(window, DARK)
        window.show()
        qapp.processEvents()
        assert spin.findChild(QLineEdit).textMargins().left() == SPIN_TEXT_INSET
    finally:
        window.hide()
        window.deleteLater()
        qapp.setStyle(previous)
