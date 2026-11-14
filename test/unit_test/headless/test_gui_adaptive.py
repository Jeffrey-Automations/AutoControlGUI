"""The adaptive building blocks: width classes, wrapping rows, stacking boxes, the fit pass, surfaces, indicators."""
import os
import subprocess  # nosec B404  # reason: runs a fixed import probe in a child interpreter
import sys

import pytest

from je_auto_control.gui.adaptive.breakpoints import (
    EXPANDED_FROM, HYSTERESIS, MEDIUM_FROM, WidthClass, classify,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# --- width classes: no Qt needed ---------------------------------------------

@pytest.mark.parametrize("width, expected", [
    (0, WidthClass.COMPACT), (MEDIUM_FROM - 1, WidthClass.COMPACT), (MEDIUM_FROM, WidthClass.MEDIUM),
    (EXPANDED_FROM - 1, WidthClass.MEDIUM), (EXPANDED_FROM, WidthClass.EXPANDED), (4000, WidthClass.EXPANDED),
])
def test_a_fresh_width_falls_in_its_plain_class(width, expected):
    assert classify(width) is expected


def test_shrinking_just_below_a_boundary_keeps_the_wider_class():
    assert classify(EXPANDED_FROM - HYSTERESIS + 1, WidthClass.EXPANDED) is WidthClass.EXPANDED
    assert classify(EXPANDED_FROM - HYSTERESIS - 1, WidthClass.EXPANDED) is WidthClass.MEDIUM
    assert classify(MEDIUM_FROM - 1, WidthClass.MEDIUM) is WidthClass.MEDIUM


def test_growing_just_past_a_boundary_keeps_the_narrower_class():
    assert classify(MEDIUM_FROM + HYSTERESIS - 1, WidthClass.COMPACT) is WidthClass.COMPACT
    assert classify(MEDIUM_FROM + HYSTERESIS, WidthClass.COMPACT) is WidthClass.MEDIUM
    assert classify(EXPANDED_FROM + 1, WidthClass.MEDIUM) is WidthClass.MEDIUM


def test_a_large_jump_skips_straight_to_its_class():
    assert classify(2000, WidthClass.COMPACT) is WidthClass.EXPANDED
    assert classify(300, WidthClass.EXPANDED) is WidthClass.COMPACT


def test_a_negative_width_is_refused():
    with pytest.raises(ValueError):
        classify(-1)


def test_importing_the_adaptive_package_loads_no_qt():
    probe = ("import sys, je_auto_control.gui.adaptive as a; "
             "assert a.classify(900).value == 'medium'; "
             "assert not any(m.startswith('PySide6') for m in sys.modules)")
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,  # nosec B603  # reason: fixed argv
                          timeout=60, check=False)
    assert done.returncode == 0, done.stderr[-1500:]


# --- widgets -------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    return widgets.QApplication.instance() or widgets.QApplication([])


def _button(text, width):
    from PySide6.QtWidgets import QPushButton
    button = QPushButton(text)
    button.setFixedWidth(width)
    return button


def test_a_flow_row_wraps_instead_of_widening(qapp):
    from PySide6.QtWidgets import QWidget
    from je_auto_control.gui.adaptive.flow_layout import FlowLayout
    host = QWidget()
    flow = FlowLayout(host, spacing=10)
    for index in range(4):
        flow.addWidget(_button(f"b{index}", 100))
    assert flow.minimumSize().width() == 100, "the minimum is the widest single item"
    one_line = flow.heightForWidth(430)
    assert flow.heightForWidth(220) > one_line, "a narrower row is taller"
    assert flow.heightForWidth(100) >= 4 * flow.itemAt(0).sizeHint().height()
    host.resize(220, flow.heightForWidth(220))
    flow.setGeometry(host.rect())
    tops = sorted({flow.itemAt(i).geometry().top() for i in range(flow.count())})
    assert len(tops) == 2, "four 100 px buttons in 220 px make two rows"
    assert all(flow.itemAt(i).geometry().right() < 220 for i in range(flow.count()))
    host.deleteLater()


def test_a_page_with_a_flow_row_scrolls_only_below_its_minimum_height(qapp):
    from PySide6.QtWidgets import QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget
    from je_auto_control.gui.adaptive.flow_layout import FlowLayout
    page = QWidget()
    layout = QVBoxLayout(page)
    flow = FlowLayout(spacing=10)
    for index in range(3):
        flow.addWidget(_button(f"b{index}", 100))
    layout.addLayout(flow)
    editor = QPlainTextEdit()
    editor.setMinimumHeight(60)
    layout.addWidget(editor, 1)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(page)
    area.resize(420, 200)          # below the page's preferred height, above its minimum
    area.show()
    for _ in range(4):
        qapp.processEvents()
    assert page.sizeHint().height() > 200
    assert area.verticalScrollBar().maximum() == 0, "a page that fits its minimum must not scroll"
    one_row = page.minimumSizeHint().height()
    area.resize(150, 400)          # 100 px buttons in ~130 px: one per row
    for _ in range(4):
        qapp.processEvents()
    assert page.minimumSizeHint().height() >= one_row + 2 * 30, "the wrapped rows raise the minimum height"
    assert all(flow.itemAt(i).geometry().bottom() < editor.geometry().top() for i in range(3)), \
        "wrapped rows never overlap what comes after them"
    area.deleteLater()


def test_a_flow_line_gives_spare_width_to_fields_and_centres_short_items(qapp):
    from PySide6.QtWidgets import QCheckBox, QLineEdit, QPlainTextEdit, QWidget
    from je_auto_control.gui.adaptive.flow_layout import FlowLayout
    host = QWidget()
    flow = FlowLayout(host, spacing=10)
    button, field, check = _button("fixed", 80), QLineEdit(), QCheckBox("Auto")
    tall = QPlainTextEdit()
    tall.setFixedSize(100, 80)
    for widget in (button, field, check, tall):
        flow.addWidget(widget)
    host.resize(700, 120)
    flow.setGeometry(host.rect())
    used = sum(w.width() for w in (button, field, check, tall)) + 3 * 10
    assert button.width() == 80, "a fixed item keeps its width"
    assert field.width() > field.sizeHint().width(), "the line edit takes the spare width"
    assert used == 700, used
    assert abs(check.geometry().center().y() - tall.geometry().center().y()) <= 1, "short items are centred on the line"
    host.deleteLater()


def test_a_hidden_item_takes_no_room_in_a_flow(qapp):
    from PySide6.QtWidgets import QWidget
    from je_auto_control.gui.adaptive.flow_layout import FlowLayout
    host = QWidget()
    flow = FlowLayout(host)
    wide, narrow = _button("wide", 300), _button("narrow", 80)
    flow.addWidget(wide)
    flow.addWidget(narrow)
    wide.hide()
    assert flow.minimumSize().width() == 80
    assert flow.takeAt(0) is not None and flow.count() == 1
    assert flow.itemAt(5) is None and flow.takeAt(5) is None
    host.deleteLater()


def test_field_pairs_wrap_as_units(qapp):
    from PySide6.QtWidgets import QLabel, QLineEdit, QWidget
    from je_auto_control.gui.adaptive.flow_layout import field_pair, flow_of
    pairs = [field_pair(QLabel(f"Label {index}"), QLineEdit()) for index in range(3)]
    host = QWidget()
    flow = flow_of(*pairs)
    host.setLayout(flow)
    widest = max(pair.minimumSizeHint().width() for pair in pairs)
    assert flow.minimumSize().width() == widest
    assert flow.count() == 3 and flow.spacing() == 12
    label, field = (pairs[0].layout().itemAt(i).widget() for i in range(2))
    assert isinstance(label, QLabel) and isinstance(field, QLineEdit)
    host.deleteLater()


def test_a_responsive_box_stacks_below_its_threshold(qapp):
    from PySide6.QtWidgets import QLabel
    from je_auto_control.gui.adaptive.responsive import ResponsiveBox
    left, right = QLabel("list"), QLabel("details")
    left.setMinimumWidth(300)
    right.setMinimumWidth(200)
    box = ResponsiveBox(left, right, stack_below=600, stretches=(2, 1))
    assert box.minimumSizeHint().width() == 300, "never more than the widest part"
    box.arrange(900)
    assert not box.stacked
    box.arrange(500)
    assert box.stacked
    box.resize(800, 300)
    box.show()
    qapp.processEvents()
    assert not box.stacked, "a resize re-arranges it"
    box.deleteLater()


def test_a_responsive_splitter_stacks_like_a_box_and_keeps_its_divider(qapp):
    from PySide6.QtWidgets import QLabel
    from je_auto_control.gui.adaptive.responsive import ResponsiveSplitter
    left, right = QLabel("frame"), QLabel("actions")
    left.setMinimumWidth(300)
    right.setMinimumWidth(200)
    splitter = ResponsiveSplitter(left, right, stack_below=600, stretches=(3, 2))
    assert splitter.minimumSizeHint().width() == 300, "never more than the widest part"
    assert not splitter.childrenCollapsible()
    splitter.resize(900, 300)
    splitter.show()
    qapp.processEvents()
    assert not splitter.stacked
    before = splitter.sizes()
    splitter.moveSplitter(before[0] - 100, 1)
    assert splitter.sizes()[0] == before[0] - 100, "the user can still drag the divider"
    splitter.resize(500, 600)
    qapp.processEvents()
    assert splitter.stacked
    splitter.hide()
    splitter.deleteLater()


def test_the_fit_pass_stops_a_long_combo_from_widening_its_page(qapp):
    from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget
    from je_auto_control.gui.adaptive.responsive import fit_to_width
    page = QWidget()
    layout = QVBoxLayout(page)
    combo = QComboBox()
    combo.addItem("A command label that goes on and on " * 4)
    form = QFormLayout()
    form.addRow("Command", combo)
    layout.addLayout(form)
    note = QLabel("A long explanatory sentence that would otherwise sit on one very wide line.")
    layout.addWidget(note)
    before = page.minimumSizeHint().width()
    adjusted = fit_to_width(page)
    after = page.minimumSizeHint().width()
    assert adjusted >= 2
    assert after < before / 2, (before, after)
    assert form.rowWrapPolicy() == QFormLayout.RowWrapPolicy.WrapLongRows
    assert note.wordWrap()
    assert fit_to_width(page) == 0, "a second pass changes nothing"
    page.deleteLater()


def test_a_missing_subtitle_shows_nothing_rather_than_its_key(qapp):
    from je_auto_control.gui.adaptive.surfaces import PageHeader, optional_text
    assert optional_text("") == ""
    assert optional_text("no_such_key_for_sure") == ""
    assert optional_text("tab_mobile_subtitle")
    header = PageHeader("tab_mobile", "no_such_key_for_sure")
    assert header.title.text() == "Mobile"
    assert header.subtitle.isHidden()
    header.deleteLater()


def test_a_page_header_is_added_once_and_only_to_a_vertical_page(qapp):
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
    from je_auto_control.gui.adaptive.surfaces import add_page_header, page_header
    page = QWidget()
    QVBoxLayout(page)
    first = add_page_header(page, "tab_mobile", "tab_mobile_subtitle")
    assert first is not None and page.layout().itemAt(0).widget() is first
    assert add_page_header(page, "tab_mobile") is first
    assert page_header(page) is first
    for layout_type in (QGridLayout, QHBoxLayout):
        other = QWidget()
        layout_type(other)
        assert add_page_header(other, "tab_mobile") is None
        other.deleteLater()
    bare = QWidget()
    assert add_page_header(bare, "tab_mobile") is None
    page.deleteLater()
    bare.deleteLater()


def test_surfaces_follow_a_language_switch(qapp):
    from PySide6.QtWidgets import QWidget, QVBoxLayout
    from je_auto_control.gui.adaptive.surfaces import Card, EmptyState, PageHeader, retranslate_surfaces
    from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
    page = QWidget()
    layout = QVBoxLayout(page)
    header = PageHeader("tab_mobile", "tab_mobile_subtitle")
    card = Card("tab_variables")
    empty = EmptyState("tab_secrets", "tab_secrets_subtitle")
    for widget in (header, card, empty):
        layout.addWidget(widget)
    previous = language_wrapper.language
    try:
        language_wrapper.reset_language("Traditional_Chinese")
        retranslate_surfaces(page)
        assert header.subtitle.text() == "探測 Android 或 iOS 裝置，並在其上執行一個行動指令。"
        assert card.title.text() == language_wrapper.translate("tab_variables")
        assert empty.hint.text() == language_wrapper.translate("tab_secrets_subtitle")
    finally:
        language_wrapper.reset_language(previous)
        page.deleteLater()
    assert card.property("role") == "card"
    assert not Card().title.isVisibleTo(card), "an untitled card shows no title row"


@pytest.mark.parametrize("radio", [False, True])
def test_indicators_are_drawn_in_the_accent_colour_when_checked(qapp, radio):
    from PySide6.QtGui import QColor, QImage, QPainter, QPalette
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QStyle, QStyleOptionButton
    from je_auto_control.gui.adaptive.style import AdaptiveStyle
    style = AdaptiveStyle()
    accent = QColor("#2563eb")
    image = QImage(32, 32, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ffffff"))
    option = QStyleOptionButton()
    option.rect = QRect(8, 8, 16, 16)
    option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_On
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    option.palette = palette
    element = QStyle.PrimitiveElement.PE_IndicatorRadioButton if radio \
        else QStyle.PrimitiveElement.PE_IndicatorCheckBox
    painter = QPainter(image)
    style.drawPrimitive(element, option, painter, None)
    painter.end()
    centre = image.pixelColor(16, 16) if radio else image.pixelColor(10, 10)
    assert abs(centre.blue() - accent.blue()) < 40 and centre.red() < 120, centre.name()
    assert style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth) == 16


def test_the_type_scale_grows_titles_with_the_text_size():
    from je_auto_control.gui.theme import type_scale_rules
    rules = type_scale_rules(12)
    assert 'QLabel[role="pageTitle"] { font-size: 18pt; }' in rules
    assert 'QLabel[role="hint"], QLabel[role="pageSubtitle"] { font-size: 11pt; }' in rules
    assert "font-size: 8pt" in type_scale_rules(6), "hints never drop below 8 pt"


def test_applying_a_theme_sets_the_application_palette_so_styled_widgets_follow_it(qapp):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QWidget
    from je_auto_control.gui.theme import DARK, LIGHT, apply_theme
    previous = qapp.palette()
    window, child = QWidget(), None
    try:
        apply_theme(window, DARK)
        assert qapp.palette().color(QPalette.ColorRole.Highlight).name() == DARK.accent
        child = QWidget(window)
        apply_theme(child, LIGHT)   # an embedded widget leaves the application alone
        assert qapp.palette().color(QPalette.ColorRole.Highlight).name() == DARK.accent
    finally:
        qapp.setPalette(previous)
        window.deleteLater()


def test_the_fit_pass_stretches_a_tables_last_column(qapp):
    from PySide6.QtWidgets import QTableWidget, QTreeWidget, QVBoxLayout, QWidget
    from je_auto_control.gui.adaptive.responsive import fit_to_width
    page = QWidget()
    table, tree = QTableWidget(0, 3), QTreeWidget()
    layout = QVBoxLayout(page)
    layout.addWidget(table)
    layout.addWidget(tree)
    table.verticalHeader().setStretchLastSection(False)
    fit_to_width(page)
    assert table.horizontalHeader().stretchLastSection()
    assert not table.verticalHeader().stretchLastSection(), "rows keep their height"
    page.deleteLater()


def test_fit_columns_caps_the_named_columns_then_refills_the_table(qapp):
    from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
    from je_auto_control.gui.adaptive.responsive import fit_columns
    table = QTableWidget(1, 3)
    table.horizontalHeader().setStretchLastSection(True)
    table.resize(900, 200)
    table.show()
    qapp.processEvents()
    for column, text in enumerate(("a", "bb", "tail")):
        table.setItem(0, column, QTableWidgetItem(text))
    header = table.horizontalHeader()
    fit_columns(table)   # sizing the last column by hand would otherwise hold it until the next resize
    assert header.length() == table.viewport().width(), "the last column takes the width the others leave"
    table.setItem(0, 1, QTableWidgetItem("x" * 120))
    fit_columns(table, capped=(1,), cap=150)
    assert table.columnWidth(1) == 150
    assert header.length() == table.viewport().width()
    table.hide()
    table.deleteLater()
