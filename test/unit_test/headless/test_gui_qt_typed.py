"""The typed accessors the tabs use in place of a cast at every call site (offscreen Qt)."""
import os
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLabel, QPushButton, QTableWidget, QTableWidgetItem  # noqa: E402

from headless._qt_settle import pump_until  # noqa: E402
from je_auto_control.gui._i18n_helpers import TranslatableMixin  # noqa: E402
from je_auto_control.gui._qt_typed import (  # noqa: E402
    as_plain, as_widget, decoded_image, filled_item, kept_selection,
)
from je_auto_control.utils.exception.exceptions import AutoControlException  # noqa: E402


@pytest.fixture(autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def test_as_widget_is_the_object_itself():
    label = QLabel("x")
    assert as_widget(label) is label
    label.deleteLater()


def test_a_filled_cell_is_returned_and_a_missing_one_is_a_typed_error():
    table = QTableWidget(1, 2)
    item = QTableWidgetItem("job-1")
    table.setItem(0, 0, item)
    assert filled_item(table, 0, 0) is item
    assert filled_item(table, 0, 0).text() == "job-1"
    with pytest.raises(AutoControlException, match="row 0, column 1"):
        filled_item(table, 0, 1)
    table.deleteLater()


def test_tr_hands_back_the_widget_it_was_given():
    """``_tr`` is generic over the widget class; at run time it has always returned its argument."""

    class _Tab(TranslatableMixin):
        """A translatable holder."""

    tab = _Tab()
    button = QPushButton()
    assert tab._tr(button, "audit_run") is button
    assert button.text() != ""
    button.deleteLater()


def test_the_scoped_enum_spellings_are_the_members_the_short_ones_named():
    assert QAbstractItemView.EditTrigger.NoEditTriggers is QAbstractItemView.NoEditTriggers
    assert Qt.ItemFlag.ItemIsEditable is Qt.ItemIsEditable
    assert Qt.ItemDataRole.UserRole is Qt.UserRole


def _encoded(image_format: str) -> bytes:
    image = QImage(6, 4, QImage.Format.Format_RGB32)
    image.fill(0xFF2040)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, image_format)
    return bytes(data)


@pytest.mark.parametrize("image_format", ["PNG", "JPEG"])
def test_an_encoded_frame_decodes_to_its_image(image_format):
    image = decoded_image(_encoded(image_format), image_format)
    assert not image.isNull()
    assert (image.width(), image.height()) == (6, 4)


@pytest.mark.parametrize("payload", [b"", b"not an image", bytes([0xFF, 0xD8, 0xFF]) + bytes(16)])
def test_bytes_that_do_not_decode_are_a_null_image(payload):
    assert decoded_image(payload, "JPEG").isNull()


def test_the_binding_still_rejects_the_bytes_format_its_stub_asks_for():
    """When this stops raising, ``QImage.fromData`` can be called directly again."""
    png = _encoded("PNG")
    with pytest.raises(ValueError):
        QImage.fromData(png, b"PNG")


# --- tables that are refilled while a row is selected ------------------------------------------------------

def _table(rows):
    table = QTableWidget(0, 2)
    _fill(table, rows)
    return table


def _fill(table, rows):
    table.setRowCount(len(rows))
    for row, name in enumerate(rows):
        table.setItem(row, 0, QTableWidgetItem(name))
        table.setItem(row, 1, QTableWidgetItem("x"))


def test_a_refill_keeps_the_selection_on_its_records():
    table = _table(["a", "b", "c", "d"])
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
    table.selectRow(1)
    table.selectRow(3)
    with kept_selection(table):
        _fill(table, ["new", "a", "b", "d"])
    assert sorted({index.row() for index in table.selectedIndexes()}) == [2, 3]
    assert table.item(table.currentRow(), 0).text() == "d"
    with kept_selection(table):
        _fill(table, ["new", "a", "b"])              # "d" is gone
    assert {index.row() for index in table.selectedIndexes()} == {2}
    assert table.currentRow() == -1
    table.deleteLater()


def test_text_that_looks_like_markup_is_shown_as_typed():
    assert as_plain("3 < 4 and plain") == "3 < 4 and plain"
    for text in ("<b>bold</b>", 'failed: <img src="file://host/x.png">'):
        shown = as_plain(text)
        assert "<img" not in shown and "<b>" not in shown and "&lt;" in shown


def _record(**fields):
    return types.SimpleNamespace(**fields)


def _scheduler(monkeypatch, rows, acted):
    from je_auto_control.gui import scheduler_tab as module
    monkeypatch.setattr(module, "default_scheduler", _record(
        is_running=False, remove_job=acted.append,
        list_jobs=lambda: [_record(job_id=name, script_path="s", interval_seconds=1.0, runs=0, enabled=True)
                           for name in rows]))
    tab = module.SchedulerTab()
    return tab, tab._refresh_table, tab._on_remove


def _hotkeys(monkeypatch, rows, acted):
    from je_auto_control.gui import hotkeys_tab as module
    monkeypatch.setattr(module, "default_hotkey_daemon", _record(
        is_running=False, unbind=acted.append,
        list_bindings=lambda: [_record(binding_id=name, combo="f1", script_path="s", fired=0) for name in rows]))
    tab = module.HotkeysTab()
    return tab, tab._refresh, tab._on_remove


def _triggers(monkeypatch, rows, acted):
    from je_auto_control.gui import triggers_tab as module
    monkeypatch.setattr(module, "default_trigger_engine", _record(
        is_running=False, remove=acted.append,
        list_triggers=lambda: [_record(trigger_id=name, fired=0, enabled=True) for name in rows]))
    tab = module.TriggersTab()
    return tab, tab._refresh, tab._on_remove


def _webhooks(monkeypatch, rows, acted):
    from je_auto_control.gui import webhooks_tab as module
    monkeypatch.setattr(module, "default_webhook_server", _record(
        is_running=False, bound_address=None, remove=acted.append,
        list_webhooks=lambda: [_record(webhook_id=name, path="/p", methods=("POST",), script_path="s", fired=0,
                                       token=None) for name in rows]))
    tab = module.WebhooksTab()
    return tab, tab._refresh, tab._on_remove


def _email(monkeypatch, rows, acted):
    from je_auto_control.gui import email_triggers_tab as module
    monkeypatch.setattr(module, "default_email_trigger_watcher", _record(
        is_running=False, remove=acted.append,
        list_triggers=lambda: [_record(trigger_id=name, host="h", port=1, username="u", mailbox="INBOX",
                                       script_path="s", fired=0, last_error="") for name in rows]))
    tab = module.EmailTriggersTab()
    return tab, tab._refresh, tab._on_remove


def _presence(monkeypatch, rows, acted):
    from je_auto_control.gui import presence_tab as module
    registry = _record(
        add_listener=lambda _listener: None, remove_listener=lambda _listener: None, unregister=acted.append,
        list=lambda: [_record(viewer_id=name, label="", role="observer", cursor_x=None, cursor_y=None,
                              last_seen_iso="") for name in rows])
    monkeypatch.setattr(module, "default_presence_registry", lambda: registry)
    tab = module.PresenceTab()
    return tab, tab.refresh, tab._on_kick


@pytest.mark.parametrize("build", [_scheduler, _hotkeys, _triggers, _webhooks, _email, _presence])
def test_a_command_goes_to_the_record_that_was_selected(build, monkeypatch):
    """The list moved under the selected row between two refreshes, and Remove / Kick hit its neighbour."""
    rows, acted = ["a", "b", "c"], []
    tab, refresh, command = build(monkeypatch, rows, acted)
    try:
        refresh()
        tab._table.setCurrentCell(1, 0)
        rows.remove("a")                                # ended, fired or left by itself
        refresh()
        command()
        assert acted == ["b"]
        rows.remove("b")
        refresh()
        command()                                       # nothing is selected any more
        assert acted == ["b"]
    finally:
        tab.dispose()
        tab.deleteLater()


def test_run_history_stays_on_the_selected_run_as_newer_ones_arrive(monkeypatch):
    from je_auto_control.gui import run_history_tab as module
    from je_auto_control.utils.run_history.history_store import RunRecord
    runs = [RunRecord(5, "manual", "x", "s.json", 1.0, 2.0, "ok", None)]
    monkeypatch.setattr(module, "default_history_store", _record(list_runs=lambda **_kwargs: list(runs)))
    tab = module.RunHistoryTab()
    try:
        tab._table.setCurrentCell(0, 0)
        runs.insert(0, RunRecord(6, "manual", "x", "s.json", 3.0, 4.0, "ok", None))
        tab._refresh()
        assert tab._selected_record().id == 5
    finally:
        tab.dispose()
        tab.deleteLater()


def test_forget_lets_go_of_the_failed_stop_that_was_selected():
    from je_auto_control.gui._stop_custody import StopCustody
    from je_auto_control.gui.failed_stops_view import FailedStopsView
    custody = StopCustody()
    ids = [custody.hold(print, OSError(str(number))) for number in range(3)]
    view = FailedStopsView(custody=custody)
    view._table.setCurrentCell(1, 0)
    custody.forget(ids[0])                              # released by a retry meanwhile
    view.refresh()
    view.forget_selected()
    assert [held.stop_id for held in custody.snapshot()] == [ids[2]]
    view.deleteLater()


def test_allow_and_block_stay_on_the_device_that_was_selected():
    from je_auto_control.gui.usb_passthrough_panel import UsbPassthroughPanel
    from je_auto_control.utils.usb.usb_devices import UsbDevice, UsbEnumerationResult
    ruled = []
    acl = _record(decide=lambda **_kwargs: "deny", verify_integrity=lambda: True,
                  remove_rule=lambda **_kwargs: None, add_rule=ruled.append)
    panel = UsbPassthroughPanel(acl=acl)
    first, second = UsbDevice(vendor_id="1111", product_id="0001"), UsbDevice(vendor_id="2222", product_id="0002")
    third = UsbDevice(vendor_id="3333", product_id="0003")
    try:
        panel._show_local_devices(UsbEnumerationResult(backend="fake", devices=[first, second, third]))
        panel._local_table.selectRow(1)
        panel._show_local_devices(UsbEnumerationResult(backend="fake", devices=[second, third]))   # one unplugged
        panel._listing.start(lambda: UsbEnumerationResult(backend="fake", devices=[]))   # no real enumeration
        panel._allow_selected()
        assert pump_until(lambda: not panel._acl_ops.running)      # the ACL is written off the GUI thread
        assert [rule.vendor_id for rule in ruled] == ["2222"]
    finally:
        panel.dispose()
        panel.deleteLater()


def _windows(monkeypatch):
    from je_auto_control.gui import window_tab as module
    monkeypatch.setattr(module, "list_windows", lambda: [(7, "notes")])
    return module.WindowManagerTab()


def _admin(_monkeypatch):
    from je_auto_control.gui.admin_console_tab import AdminConsoleTab
    return AdminConsoleTab()


def _agent(_monkeypatch):
    from je_auto_control.gui.agent_tasks_tab import AgentTasksTab
    return AgentTasksTab()


def _variables(_monkeypatch):
    from je_auto_control.gui.variables_tab import VariablesTab
    return VariablesTab()


def _built(build):
    return lambda monkeypatch: build(monkeypatch, [], [])[0]


@pytest.mark.parametrize("build", [_windows, _admin, _agent, _variables, _built(_scheduler), _built(_hotkeys),
                                   _built(_triggers)])
def test_a_table_whose_cells_name_the_target_cannot_be_typed_into(build, monkeypatch):
    """A key pressed on the selected row opened its editor, and Close / Remove acted on the typed id."""
    tab = build(monkeypatch)
    try:
        assert tab._table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    finally:
        getattr(tab, "dispose", tab.close)()
        tab.deleteLater()
