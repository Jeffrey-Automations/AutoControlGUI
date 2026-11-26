"""A translated word in a table or list cell follows a language switch (offscreen Qt; no real I/O).

Each case fills a tab's table the way its listing would -- from a fake
source, or through the method the listing's answer reaches -- switches to
Japanese and calls ``retranslate``. The translated cells must then read as
their keys do in Japanese, the data cells must be what they were, and the rows
must still be there: a switch re-renders what the table holds, it does not
list again.
"""
import os
import types

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QTableWidget  # noqa: E402

from je_auto_control.gui._i18n_cells import (  # noqa: E402
    keyed_cell, retranslate_cells, set_keyed, set_rendered,
)
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def english():
    previous = language_wrapper.language
    language_wrapper.reset_language("English")
    yield
    language_wrapper.reset_language(previous)


def _word(key):
    return language_wrapper.translate(key, key)


def _dispose(qapp, tab):
    getattr(tab, "dispose", tab.close)()
    tab.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _switch(tab, table, cells):
    """``cells`` maps (row, column) to a key: check them in English, switch, re-translate, check in Japanese."""
    data = {(row, column): table.item(row, column).text()
            for row in range(table.rowCount()) for column in range(table.columnCount())
            if (row, column) not in cells and table.item(row, column) is not None}
    rows = table.rowCount()
    for (row, column), key in cells.items():
        assert table.item(row, column).text() == _word(key)
    english_words = {place: _word(key) for place, key in cells.items()}
    language_wrapper.reset_language("Japanese")
    tab.retranslate()
    assert table.rowCount() == rows, "the switch listed again"
    assert any(_word(key) != english_words[place] for place, key in cells.items()), "the case proves nothing"
    for place, key in cells.items():
        assert table.item(*place).text() == _word(key)
    assert {place: table.item(*place).text() for place in data} == data


# --- the helper itself ------------------------------------------------------

def test_a_keyed_cell_keeps_its_row_selection_and_sort(qapp, english):
    table = QTableWidget(2, 2)
    table.setSortingEnabled(False)
    for row, (name, key) in enumerate((("b", "tr_yes"), ("a", "tr_no"))):
        table.setItem(row, 0, keyed_cell(key))
        table.setItem(row, 1, set_keyed(keyed_cell("tr_yes"), "admin_health_ok", Qt.ItemDataRole.ToolTipRole))
        table.item(row, 1).setText(name)
    table.setSortingEnabled(True)
    table.sortItems(1)
    table.selectRow(1)
    edits = []
    table.itemChanged.connect(edits.append)
    language_wrapper.reset_language("Japanese")
    assert retranslate_cells(table) == 4
    assert [table.item(row, 1).text() for row in range(2)] == ["a", "b"], "a text set over a key is left alone"
    assert [table.item(row, 0).text() for row in range(2)] == [_word("tr_no"), _word("tr_yes")]
    assert table.item(0, 1).toolTip() == _word("admin_health_ok")
    assert [item.text() for item in table.selectedItems()] == [_word("tr_yes"), "b"]
    assert edits == [], "a language switch reached itemChanged"


def test_a_rendered_list_item_is_read_again(qapp, english):
    view = QListWidget()
    item = QListWidgetItem()
    set_rendered(item, lambda: _word("rd_webrtc_unnamed") + " - host")
    view.addItem(item)
    view.addItem("plain")
    language_wrapper.reset_language("Japanese")
    assert retranslate_cells(view) == 1
    assert [view.item(row).text() for row in range(2)] == [_word("rd_webrtc_unnamed") + " - host", "plain"]


def test_keyed_cells_fill_their_fields(qapp, english):
    item = keyed_cell("rd_webrtc_stat_loss", pct="1.5")
    assert item.text() == "loss 1.5%"
    table = QTableWidget(1, 1)
    table.setItem(0, 0, item)
    language_wrapper.reset_language("Japanese")
    retranslate_cells(table)
    language_wrapper.reset_language("Simplified_Chinese")
    retranslate_cells(table)
    assert table.item(0, 0).text() == _word("rd_webrtc_stat_loss").replace("{pct}", "1.5"), "a second switch"


# --- the tabs ---------------------------------------------------------------

def test_the_scheduler_enabled_column(qapp, english, monkeypatch):
    from je_auto_control.gui import scheduler_tab
    tab = scheduler_tab.SchedulerTab()
    try:
        job = types.SimpleNamespace(job_id="j1", script_path="a.json", interval_seconds=5.0, runs=3, enabled=False)
        with monkeypatch.context() as patch:
            patch.setattr(scheduler_tab, "default_scheduler", types.SimpleNamespace(list_jobs=lambda: [job]))
            tab._refresh_table()
        _switch(tab, tab._table, {(0, 4): "tr_no"})
    finally:
        _dispose(qapp, tab)


def test_the_triggers_enabled_column(qapp, english):
    from je_auto_control.gui.triggers_tab import TriggersTab
    tab = TriggersTab()
    try:
        tab._fill_table([types.SimpleNamespace(trigger_id="t1", fired=2, enabled=True)])
        _switch(tab, tab._table, {(0, 4): "tr_yes"})
    finally:
        _dispose(qapp, tab)


def test_the_webhooks_token_column(qapp, english, monkeypatch):
    from je_auto_control.gui import webhooks_tab
    tab = webhooks_tab.WebhooksTab()
    try:
        hook = types.SimpleNamespace(webhook_id="w1", path="/run", methods=["POST"], script_path="a.json",
                                     fired=0, token="secret")
        with monkeypatch.context() as patch:
            patch.setattr(webhooks_tab, "default_webhook_server", types.SimpleNamespace(list_webhooks=lambda: [hook]))
            tab._fill_table()
        _switch(tab, tab._table, {(0, 5): "wh_yes"})
    finally:
        _dispose(qapp, tab)


def test_the_admin_console_health_column(qapp, english):
    from je_auto_control.gui.admin_console_tab import AdminConsoleTab
    from je_auto_control.utils.admin.admin_client import AdminHost, HostStatus
    tab = AdminConsoleTab()
    try:
        hosts = [AdminHost("up", "http://127.0.0.1:1", ""), AdminHost("down", "http://127.0.0.1:2", "")]
        tab._client = types.SimpleNamespace(list_hosts=lambda: hosts)
        tab._refresh_table([HostStatus("up", "", True, 4.0), HostStatus("down", "", False, 9.0)])
        _switch(tab, tab._table, {(0, 2): "admin_health_ok", (1, 2): "admin_health_down"})
    finally:
        _dispose(qapp, tab)


def test_the_device_matrix_result_column(qapp, english):
    from je_auto_control.gui.device_matrix_tab import DeviceMatrixTab
    tab = DeviceMatrixTab()
    try:
        results = [{"device_id": "d1", "platform": "android", "success": True, "duration_s": 1.0},
                   {"device_id": "d2", "platform": "ios", "success": False, "duration_s": 2.0, "error": "boom"}]
        tab._render({"results": results, "passed": 1, "failed": 1, "total": 2})
        _switch(tab, tab._table, {(0, 2): "dm_result_ok", (1, 2): "dm_result_fail"})
    finally:
        _dispose(qapp, tab)


def test_the_self_healing_verified_column(qapp, english):
    from je_auto_control.gui.self_healing_tab import SelfHealingTab
    from je_auto_control.utils.self_healing.heal_log import HealEvent
    tab = SelfHealingTab()
    try:
        tab._show_log([HealEvent(timestamp="t", method="template", coordinates=None, duration_ms=1.0)])
        _switch(tab, tab._table, {(0, 5): "self_heal_unknown"})
    finally:
        _dispose(qapp, tab)


def test_the_usb_share_policy_column(qapp, english, tmp_path):
    from je_auto_control.gui.usb_passthrough_panel import UsbPassthroughPanel
    from je_auto_control.utils.usb.passthrough import UsbAcl
    from je_auto_control.utils.usb.usb_devices import UsbDevice, UsbEnumerationResult
    panel = UsbPassthroughPanel(acl=UsbAcl(path=tmp_path / "acl.json"))
    try:
        device = UsbDevice(vendor_id="1050", product_id="0407")
        policy = panel._acl.decide(vendor_id="1050", product_id="0407", serial=None)
        panel._fill_local_table(UsbEnumerationResult(backend="fake", devices=[device]))
        _switch(panel, panel._local_table, {(0, 4): f"usb_share_policy_{policy}"})
    finally:
        _dispose(qapp, panel)


def test_the_audit_log_all_entry(qapp, english):
    from je_auto_control.gui.audit_log_tab import AuditLogTab, build_event_type_choices
    tab = AuditLogTab()
    try:
        tab._sync_event_type_dropdown(build_event_type_choices(["custom"]))
        assert tab._type_filter.itemText(0) == _word("audit_filter_all")
        assert tab._current_event_type_filter() is None
        language_wrapper.reset_language("Japanese")
        tab.retranslate()
        assert tab._type_filter.itemText(0) == _word("audit_filter_all") != "(all)"
        assert tab._type_filter.currentText() == _word("audit_filter_all")
        assert tab._current_event_type_filter() is None, "the translated entry is a filter of its own"
        tab._type_filter.setCurrentIndex(tab._type_filter.findData("custom"))
        tab._sync_event_type_dropdown(build_event_type_choices(["custom"]))
        assert tab._current_event_type_filter() == "custom", "a refresh lost the chosen type"
    finally:
        _dispose(qapp, tab)


def test_the_remote_desktop_lists_read_their_placeholders_again(qapp, english):
    from je_auto_control.gui.remote_desktop.webrtc_dialogs import AddressBookList, TrustedViewersList
    trusted, book = TrustedViewersList(), AddressBookList()
    try:
        trusted.populate([{"viewer_id": "abcdef0123456789"}])
        book.populate([{"host_id": "h-1"}])
        assert trusted.item(0).text() == "(unlabeled) - abcdef01..."
        assert book.item(0).text() == "(unnamed) - h-1"
        language_wrapper.reset_language("Japanese")
        retranslate_cells(trusted)
        retranslate_cells(book)
        assert trusted.item(0).text() == _word("rd_webrtc_unlabeled") + " - abcdef01..."
        assert book.item(0).text() == _word("rd_webrtc_unnamed") + " - h-1"
        assert trusted.item(0).data(Qt.ItemDataRole.UserRole) == "abcdef0123456789"
    finally:
        for view in (trusted, book):
            _dispose(qapp, view)
