"""The file reads and writes that follow a tab's file dialog no longer hold the GUI thread.

Offscreen Qt against fakes: every file dialog is faked, and the read or write
behind it waits on a gate, so the test sees the slot return first, the tab
report itself busy, and the outcome arrive later on the GUI thread.
``dispose()`` (or closing a dialog) while the call is out drops its outcome.
"""
import builtins
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
    """A backend call that blocks until released, remembers where it ran, then delegates or answers."""

    def __init__(self, result=None, error=None, then=None) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.threads: list = []
        self.calls: list = []
        self.result = result
        self.error = error
        self.then = then

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.threads.append(threading.get_ident())
        self.entered.set()
        self.release.wait(_WAIT)
        if self.error is not None:
            raise self.error
        if self.then is not None:
            return self.then(*args, **kwargs)
        return self.result

    def off_gui_thread(self) -> bool:
        return bool(self.threads) and all(ident != threading.get_ident() for ident in self.threads)


@pytest.fixture
def boxes(monkeypatch):
    QApplication.instance() or QApplication([])
    shown = []
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, lambda *args: shown.append(args[-1]))
    # No real dialog ever opens: a test that needs a path patches the one it uses.
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: ("", ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: "")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("", False))
    return shown


def _returns_at_once(slot, *args) -> None:
    started = time.monotonic()
    slot(*args)
    assert time.monotonic() - started < 5.0, "the slot held the GUI thread"


def _pick_open(monkeypatch, path) -> None:
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))


def _pick_save(monkeypatch, path) -> None:
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))


def _gated_open(monkeypatch, module) -> _Gate:
    """Gate the module's ``open``: the file is still really opened, once the gate is released."""
    gate = _Gate(then=builtins.open)
    monkeypatch.setattr(module, "open", gate, raising=False)
    return gate


# --- DAG editor ---------------------------------------------------------------------------------------------

def test_loading_a_dag_file_runs_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui import dag_tab as module
    source = tmp_path / "dag.json"
    source.write_text('{"nodes": []}', encoding="utf-8")
    _pick_open(monkeypatch, source)
    gate = _gated_open(monkeypatch, module)
    tab = module.DagTab()
    _returns_at_once(tab._on_load)
    assert gate.entered.wait(_WAIT)
    assert tab._status_label.text() == _t("task_running")
    tab._on_load()                                  # one load at a time
    assert tab._status_label.text() == _t("task_busy")
    gate.release.set()
    assert pump_until(lambda: not tab._loading.running)
    assert gate.off_gui_thread() and len(gate.calls) == 1
    assert tab._editor.toPlainText() == '{"nodes": []}'
    tab.dispose()
    tab.deleteLater()


def test_a_dag_file_that_cannot_be_read_is_reported_in_the_tab(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui import dag_tab as module
    _pick_open(monkeypatch, tmp_path / "missing.json")
    tab = module.DagTab()
    tab._editor.setPlainText("kept")
    tab._on_load()
    assert pump_until(lambda: not tab._loading.running)
    assert tab._status_label.text().startswith(_t("dag_error"))
    assert tab._editor.toPlainText() == "kept"
    tab.dispose()
    tab.deleteLater()


def test_disposing_the_dag_tab_drops_a_load_still_out(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui import dag_tab as module
    source = tmp_path / "dag.json"
    source.write_text('{"nodes": []}', encoding="utf-8")
    _pick_open(monkeypatch, source)
    gate = _gated_open(monkeypatch, module)
    tab = module.DagTab()
    tab._on_load()
    assert gate.entered.wait(_WAIT)
    tab.dispose()
    gate.release.set()
    pump_until(lambda: False, timeout=0.5)
    assert tab._editor.toPlainText() == ""
    tab.deleteLater()


# --- WebRTC host: trust list --------------------------------------------------------------------------------

def _host_panel(tmp_path):
    pytest.importorskip("av")
    pytest.importorskip("aiortc")
    from je_auto_control.gui.remote_desktop import webrtc_panel
    from je_auto_control.utils.remote_desktop.trust_list import TrustList
    panel = webrtc_panel._WebRTCHostPanel()
    panel._trust_list = TrustList(tmp_path / "trusted.json")      # never the user's own list
    return panel


def _close(panel) -> None:
    panel.dispose()
    panel.deleteLater()


def test_exporting_the_trust_list_writes_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui.remote_desktop import _helpers
    panel = _host_panel(tmp_path)
    panel._trust_list.add("viewer-1", label="desk")
    target = tmp_path / "export.json"
    _pick_save(monkeypatch, target)
    _pick_open(monkeypatch, target)
    gate = _gated_open(monkeypatch, _helpers)
    _returns_at_once(panel._on_export_trust)
    assert gate.entered.wait(_WAIT)
    panel._on_import_trust()                        # one trust-list file at a time
    assert boxes == [_t("task_busy")]
    gate.release.set()
    assert pump_until(lambda: panel._trust_task is None)
    assert gate.off_gui_thread()
    import json
    assert [entry["viewer_id"] for entry in json.loads(target.read_text(encoding="utf-8"))["viewers"]] == [
        "viewer-1"]
    _close(panel)


def test_importing_a_trust_list_reads_and_adds_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui.remote_desktop import _helpers
    source = tmp_path / "import.json"
    source.write_text('{"viewers": [{"viewer_id": "v1", "label": "a"}, {"viewer_id": 5}]}', encoding="utf-8")
    _pick_open(monkeypatch, source)
    panel = _host_panel(tmp_path)
    gate = _gated_open(monkeypatch, _helpers)
    _returns_at_once(panel._on_import_trust)
    assert gate.entered.wait(_WAIT)
    assert panel._trusted_list.count() == 0
    gate.release.set()
    assert pump_until(lambda: panel._trust_task is None)
    assert gate.off_gui_thread()
    assert boxes == [_t("rd_webrtc_trust_import_done").format(n=1)]
    assert [entry["viewer_id"] for entry in panel._trust_list.list_entries()] == ["v1"]
    assert panel._trusted_list.count() == 1
    _close(panel)


def test_a_trust_import_that_cannot_be_read_is_reported(boxes, monkeypatch, tmp_path):
    source = tmp_path / "import.json"
    source.write_bytes(b"\xff\xfe\x00binary")
    _pick_open(monkeypatch, source)
    panel = _host_panel(tmp_path)
    panel._on_import_trust()
    assert pump_until(lambda: panel._trust_task is None)
    assert len(boxes) == 1 and boxes[0] != _t("rd_webrtc_trust_import_done").format(n=0)
    _close(panel)


def test_removing_and_clearing_trust_write_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    panel = _host_panel(tmp_path)
    panel._trust_list.add("v1")
    panel._trust_list.add("v2")
    panel._refresh_trusted_list()
    remove = _Gate(then=panel._trust_list.remove)
    monkeypatch.setattr(panel._trust_list, "remove", remove)
    _returns_at_once(panel._on_remove_trust, "v1")
    assert remove.entered.wait(_WAIT)
    remove.release.set()
    assert pump_until(lambda: panel._trust_task is None)
    assert remove.off_gui_thread() and panel._trusted_list.count() == 1
    clear = _Gate(then=panel._trust_list.clear)
    monkeypatch.setattr(panel._trust_list, "clear", clear)
    _returns_at_once(panel._on_clear_trust)
    assert clear.entered.wait(_WAIT)
    clear.release.set()
    assert pump_until(lambda: panel._trust_task is None)
    assert clear.off_gui_thread() and panel._trusted_list.count() == 0
    _close(panel)


def test_disposing_the_host_panel_drops_a_trust_import_still_out(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui.remote_desktop import _helpers
    source = tmp_path / "import.json"
    source.write_text('{"viewers": [{"viewer_id": "v1"}]}', encoding="utf-8")
    _pick_open(monkeypatch, source)
    panel = _host_panel(tmp_path)
    gate = _gated_open(monkeypatch, _helpers)
    panel._on_import_trust()
    assert gate.entered.wait(_WAIT)
    panel.dispose()
    gate.release.set()
    pump_until(lambda: False, timeout=0.5)
    assert boxes == [] and panel._trusted_list.count() == 0
    panel.deleteLater()


# --- WebRTC viewer: address book, Wake-on-LAN, session bookkeeping ------------------------------------------

def _viewer_panel(tmp_path):
    pytest.importorskip("av")
    pytest.importorskip("aiortc")
    from je_auto_control.gui.remote_desktop import webrtc_panel
    from je_auto_control.utils.remote_desktop.address_book import AddressBook
    from je_auto_control.utils.remote_desktop.fingerprint import KnownHosts
    panel = webrtc_panel._WebRTCViewerPanel()
    panel._address_book = AddressBook(tmp_path / "book.json")       # never the user's own book
    panel._known_hosts = KnownHosts(tmp_path / "known.json")
    return panel


def test_exporting_and_importing_the_address_book_run_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui.remote_desktop import _helpers
    panel = _viewer_panel(tmp_path)
    panel._address_book.upsert(host_id="123", server_url="http://s")       # NOSONAR never contacted
    target = tmp_path / "export.json"
    _pick_save(monkeypatch, target)
    _pick_open(monkeypatch, target)
    gate = _gated_open(monkeypatch, _helpers)
    _returns_at_once(panel._on_ab_export)
    assert gate.entered.wait(_WAIT)
    panel._on_ab_import()                           # one address-book call at a time
    assert boxes == [_t("task_busy")]
    gate.release.set()
    assert pump_until(lambda: panel._book_task is None)
    assert gate.off_gui_thread() and target.exists()
    panel._address_book.clear()
    gate.release.clear()
    gate.entered.clear()
    _returns_at_once(panel._on_ab_import)
    assert gate.entered.wait(_WAIT)
    gate.release.set()
    assert pump_until(lambda: panel._book_task is None)
    assert boxes[-1] == _t("rd_webrtc_ab_import_done").format(n=1)
    assert [entry["host_id"] for entry in panel._address_book.list_entries()] == ["123"]
    _close(panel)


@pytest.mark.parametrize("slot, method", [
    ("_on_save_current_address", "upsert"), ("_on_address_removed", "remove"),
    ("_on_address_favorite", "toggle_favorite"), ("_on_ab_clear", "clear"),
])
def test_address_book_writes_run_off_the_gui_thread(boxes, monkeypatch, tmp_path, slot, method):
    panel = _viewer_panel(tmp_path)
    panel._address_book.upsert(host_id="123", server_url="http://s")       # NOSONAR never contacted
    panel._host_id_edit.setText("456")
    panel._server_edit.setText("http://s")                                 # NOSONAR never contacted
    gate = _Gate(then=getattr(panel._address_book, method))
    monkeypatch.setattr(panel._address_book, method, gate)
    entry = {"host_id": "123", "server_url": "http://s"}                   # NOSONAR never contacted
    args = (entry,) if slot in ("_on_address_removed", "_on_address_favorite") else ()
    _returns_at_once(getattr(panel, slot), *args)
    assert gate.entered.wait(_WAIT)
    gate.release.set()
    assert pump_until(lambda: panel._book_task is None)
    assert gate.off_gui_thread() and boxes == []
    _close(panel)


def test_wake_on_lan_sends_and_remembers_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui.remote_desktop import webrtc_viewer_address_book as module
    panel = _viewer_panel(tmp_path)
    panel._address_book.upsert(host_id="123", server_url="http://s")       # NOSONAR never contacted
    panel._refresh_address_book()
    entry = panel._address_book.list_entries()[0]
    monkeypatch.setattr(panel._address_list, "selected_entry", lambda: entry)
    answers = iter([("aa:bb:cc:dd:ee:ff", True), ("192.0.2.255", True)])
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: next(answers))
    gate = _Gate()
    monkeypatch.setattr(module, "send_magic_packet", gate)
    _returns_at_once(panel._on_wake_on_lan)
    assert gate.entered.wait(_WAIT)
    gate.release.set()
    assert pump_until(lambda: panel._book_task is None)
    assert gate.off_gui_thread()
    assert gate.calls == [(("aa:bb:cc:dd:ee:ff",), {"broadcast_address": "192.0.2.255"})]
    assert boxes == [_t("rd_webrtc_wol_sent")]
    assert panel._address_book.list_entries()[0]["mac_address"] == "aa:bb:cc:dd:ee:ff"
    _close(panel)


def test_a_failed_wake_on_lan_is_reported_and_not_remembered(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui.remote_desktop import webrtc_viewer_address_book as module
    panel = _viewer_panel(tmp_path)
    answers = iter([("not-a-mac", True), ("", True)])
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: next(answers))
    gate = _Gate(error=ValueError("bad MAC"))
    gate.release.set()
    monkeypatch.setattr(module, "send_magic_packet", gate)
    panel._on_wake_on_lan()
    assert pump_until(lambda: panel._book_task is None)
    assert boxes == ["bad MAC"]
    _close(panel)


def test_an_authenticated_session_is_recorded_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    panel = _viewer_panel(tmp_path)
    monkeypatch.setattr(panel, "_start_stats_polling", lambda: None)
    monkeypatch.setattr(panel, "_ensure_screen_window", lambda: _Window())
    panel._host_id_edit.setText("123456789")
    panel._server_edit.setText("http://s")                                 # NOSONAR never contacted
    gate = _Gate(then=panel._address_book.upsert)
    monkeypatch.setattr(panel._address_book, "upsert", gate)
    _returns_at_once(panel._on_auth, True)
    assert gate.entered.wait(_WAIT)
    gate.release.set()
    assert pump_until(lambda: panel._address_list.count() == 1)
    assert gate.off_gui_thread()
    assert panel._known_hosts.last_seen("123456789") is not None
    _close(panel)


class _Window:
    def show(self):
        pass

    def raise_(self):
        pass

    def activateWindow(self):  # noqa: N802  # reason: the Qt name the panel calls
        pass


# --- WebRTC viewer: known hosts dialog ----------------------------------------------------------------------

def _known_hosts_dialog(tmp_path):
    from je_auto_control.gui.remote_desktop.webrtc_known_hosts import KnownHostsDialog
    from je_auto_control.utils.remote_desktop.fingerprint import KnownHosts
    known = KnownHosts(tmp_path / "known.json")
    return KnownHostsDialog(known), known


def test_exporting_known_hosts_writes_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui.remote_desktop import _helpers
    dialog, known = _known_hosts_dialog(tmp_path)
    known.remember("123", "a" * 64)
    target = tmp_path / "export.json"
    _pick_save(monkeypatch, target)
    gate = _gated_open(monkeypatch, _helpers)
    _returns_at_once(dialog._on_export)
    assert gate.entered.wait(_WAIT)
    dialog._on_import()                             # one known-hosts file at a time
    assert boxes == [_t("task_busy")]
    gate.release.set()
    assert pump_until(lambda: dialog._write_task is None)
    assert gate.off_gui_thread() and "123" in target.read_text(encoding="utf-8")
    dialog.deleteLater()


def test_importing_known_hosts_reads_then_pins_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui.remote_desktop import webrtc_known_hosts as module
    dialog, known = _known_hosts_dialog(tmp_path)
    known.remember("old", "b" * 64)
    dialog._refresh()
    source = tmp_path / "import.json"
    source.write_text('{"old": "' + "c" * 64 + '", "new": {"dtls_fp": "' + "d" * 64 + '"}, "bad": 5}',
                      encoding="utf-8")
    _pick_open(monkeypatch, source)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    read = _gated_open(monkeypatch, module)
    pin = _Gate(then=known.remember_dtls_fingerprint)
    monkeypatch.setattr(known, "remember_dtls_fingerprint", pin)
    _returns_at_once(dialog._on_import)
    assert read.entered.wait(_WAIT)
    read.release.set()
    assert pump_until(pin.entered.is_set)           # the overwrite of "old" was declined
    assert dialog._table.rowCount() == 1
    pin.release.set()
    assert pump_until(lambda: dialog._write_task is None and dialog._read_task is None)
    assert read.off_gui_thread() and pin.off_gui_thread()
    assert boxes == [_t("rd_webrtc_kh_import_done").format(added=1, skipped=1)]
    assert known.fingerprint_for("old") == "b" * 64 and known.dtls_fingerprint_for("new") == "d" * 64
    assert dialog._table.rowCount() == 2
    dialog.deleteLater()


def test_forgetting_known_hosts_writes_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    dialog, known = _known_hosts_dialog(tmp_path)
    known.remember("123", "a" * 64)
    dialog._refresh()
    gate = _Gate(then=known.forget)
    monkeypatch.setattr(known, "forget", gate)
    _returns_at_once(dialog._on_clear_all)
    assert gate.entered.wait(_WAIT)
    assert dialog._table.rowCount() == 1
    gate.release.set()
    assert pump_until(lambda: dialog._write_task is None)
    assert gate.off_gui_thread() and dialog._table.rowCount() == 0
    dialog.deleteLater()


def test_closing_the_known_hosts_dialog_drops_an_import_still_out(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui.remote_desktop import webrtc_known_hosts as module
    dialog, known = _known_hosts_dialog(tmp_path)
    source = tmp_path / "import.json"
    source.write_text('{"new": "' + "c" * 64 + '"}', encoding="utf-8")
    _pick_open(monkeypatch, source)
    read = _gated_open(monkeypatch, module)
    dialog._on_import()
    assert read.entered.wait(_WAIT)
    dialog.reject()
    read.release.set()
    pump_until(lambda: False, timeout=0.5)
    assert boxes == [] and known.fingerprint_for("new") is None
    dialog.deleteLater()


# --- USB passthrough: the ACL ------------------------------------------------------------------------------

def _usb_panel(tmp_path):
    from je_auto_control.gui import usb_passthrough_panel as module
    from je_auto_control.utils.usb.passthrough import UsbAcl
    acl = UsbAcl(path=tmp_path / "acl.json", hmac_key=b"k" * 32)
    panel = module.UsbPassthroughPanel(acl=acl)
    panel._listing.start(lambda: module.UsbEnumerationResult(backend="fake", devices=[]))   # no real listing
    return panel, acl


def _select_device(panel) -> None:
    from PySide6.QtWidgets import QTableWidgetItem
    panel._local_table.setRowCount(1)
    for column, text in enumerate(("1050", "0407", "key", "")):
        panel._local_table.setItem(0, column, QTableWidgetItem(text))
    panel._local_table.setCurrentCell(0, 0)


@pytest.mark.parametrize("slot, name", [("_export_acl", "export_acl_to_file"),
                                        ("_import_acl", "import_acl_from_file")])
def test_exporting_and_importing_the_usb_acl_run_off_the_gui_thread(boxes, monkeypatch, tmp_path, slot, name):
    from je_auto_control.gui import usb_passthrough_panel as module
    panel, _acl = _usb_panel(tmp_path)
    _pick_save(monkeypatch, tmp_path / "out.json")
    _pick_open(monkeypatch, tmp_path / "in.json")
    gate = _Gate(result=2)
    monkeypatch.setattr(module, name, gate)
    _returns_at_once(getattr(panel, slot))
    assert gate.entered.wait(_WAIT)
    assert panel._viewer_status.text() == _t("task_running")
    panel._export_acl()                             # one ACL task at a time
    assert panel._viewer_status.text() == _t("task_busy")
    gate.release.set()
    assert pump_until(lambda: not panel._acl_ops.running)
    assert gate.off_gui_thread() and len(gate.calls) == 1
    expected = _t("usb_share_acl_exported") if slot == "_export_acl" else _t(
        "usb_share_acl_imported").format(count=2)
    assert panel._viewer_status.text() == expected
    panel.dispose()
    panel.deleteLater()


def test_a_usb_acl_import_that_fails_is_reported(boxes, monkeypatch, tmp_path):
    panel, _acl = _usb_panel(tmp_path)
    _pick_open(monkeypatch, tmp_path / "missing.json")
    panel._import_acl()
    assert pump_until(lambda: not panel._acl_ops.running)
    assert panel._viewer_status.text().startswith(_t("usb_share_acl_import_failed").split("{")[0])
    panel.dispose()
    panel.deleteLater()


def test_allowing_a_usb_device_writes_the_acl_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    panel, acl = _usb_panel(tmp_path)
    _select_device(panel)
    gate = _Gate(then=acl.add_rule)
    monkeypatch.setattr(acl, "add_rule", gate)
    _returns_at_once(panel._allow_selected)
    assert gate.entered.wait(_WAIT)
    assert acl.list_rules() == []
    gate.release.set()
    assert pump_until(lambda: not panel._acl_ops.running)
    assert gate.off_gui_thread()
    assert [(rule.vendor_id, rule.allow) for rule in acl.list_rules()] == [("1050", True)]
    assert panel._viewer_status.text() == _t("usb_share_allowed").format(vid="1050", pid="0407")
    panel.dispose()
    panel.deleteLater()


def test_the_usb_acl_integrity_check_runs_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui import usb_passthrough_panel as module
    from je_auto_control.utils.usb.passthrough import UsbAcl
    gate = _Gate(result=False)
    acl = UsbAcl(path=tmp_path / "acl.json", hmac_key=b"k" * 32)
    monkeypatch.setattr(acl, "verify_integrity", gate)
    started = time.monotonic()
    panel = module.UsbPassthroughPanel(acl=acl)
    assert time.monotonic() - started < 5.0, "the badge waited for the ACL file"
    assert gate.entered.wait(_WAIT)
    gate.release.set()
    assert pump_until(lambda: not panel._integrity.running)
    assert gate.off_gui_thread()
    assert panel._viewer_status.text() == _t("usb_share_acl_tampered")
    panel.dispose()
    panel.deleteLater()


def test_disposing_the_usb_panel_drops_an_acl_import_still_out(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui import usb_passthrough_panel as module
    panel, _acl = _usb_panel(tmp_path)
    _pick_open(monkeypatch, tmp_path / "in.json")
    gate = _Gate(result=3)
    monkeypatch.setattr(module, "import_acl_from_file", gate)
    panel._import_acl()
    assert gate.entered.wait(_WAIT)
    panel.dispose()
    gate.release.set()
    pump_until(lambda: False, timeout=0.5)
    assert panel._viewer_status.text() == _t("task_running")
    panel.deleteLater()


# --- admin console: add and remove hosts --------------------------------------------------------------------

def _admin_tab(monkeypatch, tmp_path):
    from je_auto_control.gui import admin_console_tab as module
    from je_auto_control.utils.admin.admin_client import AdminConsoleClient
    client = AdminConsoleClient(persist_path=tmp_path / "hosts.json")
    monkeypatch.setattr(module, "default_admin_console", lambda: client)
    tab = module.AdminConsoleTab()
    tab._thumb_interval.setValue(0)                 # no thumbnail polling
    return tab, client


def test_adding_an_admin_host_writes_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    tab, client = _admin_tab(monkeypatch, tmp_path)
    gate = _Gate(then=client.add_host)
    monkeypatch.setattr(client, "add_host", gate)
    tab._label_input.setText("alpha")
    tab._url_input.setText("http://a.invalid:9939")         # NOSONAR never contacted
    tab._token_input.setText("tok")
    _returns_at_once(tab._on_add)
    assert gate.entered.wait(_WAIT)
    assert tab._broadcast_status.text() == _t("task_running")
    tab._on_add()                                   # one host edit at a time
    assert tab._broadcast_status.text() == _t("task_busy")
    gate.release.set()
    assert pump_until(lambda: not tab._edits.running)
    assert gate.off_gui_thread() and len(gate.calls) == 1
    assert tab._table.rowCount() == 1 and tab._label_input.text() == ""
    tab.dispose()
    tab.deleteLater()


def test_a_rejected_admin_host_is_reported_and_its_fields_kept(boxes, monkeypatch, tmp_path):
    tab, _client = _admin_tab(monkeypatch, tmp_path)
    tab._label_input.setText("alpha")
    tab._on_add()                                   # no URL
    assert pump_until(lambda: not tab._edits.running)
    assert len(boxes) == 1 and tab._label_input.text() == "alpha" and tab._table.rowCount() == 0
    tab.dispose()
    tab.deleteLater()


def test_removing_admin_hosts_writes_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    tab, client = _admin_tab(monkeypatch, tmp_path)
    client.add_host("alpha", "http://a.invalid:9939", "tok")    # NOSONAR never contacted
    tab._refresh_table()
    tab._table.selectRow(0)
    gate = _Gate(then=client.remove_host)
    monkeypatch.setattr(client, "remove_host", gate)
    _returns_at_once(tab._on_remove)
    assert gate.entered.wait(_WAIT)
    assert tab._table.rowCount() == 1
    gate.release.set()
    assert pump_until(lambda: not tab._edits.running)
    assert gate.off_gui_thread() and tab._table.rowCount() == 0
    tab.dispose()
    tab.deleteLater()


def test_disposing_the_admin_console_drops_a_host_edit_still_out(boxes, monkeypatch, tmp_path):
    tab, client = _admin_tab(monkeypatch, tmp_path)
    gate = _Gate(then=client.add_host)
    monkeypatch.setattr(client, "add_host", gate)
    tab._label_input.setText("alpha")
    tab._url_input.setText("http://a.invalid:9939")         # NOSONAR never contacted
    tab._token_input.setText("tok")
    tab._on_add()
    assert gate.entered.wait(_WAIT)
    tab.dispose()
    gate.release.set()
    pump_until(lambda: False, timeout=0.5)
    assert tab._table.rowCount() == 0 and tab._label_input.text() == "alpha"
    tab.deleteLater()


# --- Quick Connect: the Recent list ------------------------------------------------------------------------

def _quick_connect(monkeypatch, tmp_path):
    from je_auto_control.gui.remote_desktop import connection_screen
    from je_auto_control.utils.remote_desktop.address_book import AddressBook
    from je_auto_control.utils.remote_desktop.registry import registry
    monkeypatch.setattr(registry, "_viewer", None)
    monkeypatch.setattr(registry, "_ws_viewer", None)
    screen = connection_screen.QuickConnectScreen()
    screen._book = AddressBook(tmp_path / "book.json")             # never the user's own book
    return screen


def test_a_connected_target_is_remembered_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    screen = _quick_connect(monkeypatch, tmp_path)
    gate = _Gate(then=screen._book.upsert)
    monkeypatch.setattr(screen._book, "upsert", gate)
    _returns_at_once(screen._remember_tcp, "127.0.0.1", 9938)
    assert gate.entered.wait(_WAIT)
    gate.release.set()
    assert pump_until(lambda: screen._recent.count() == 1)
    assert gate.off_gui_thread()
    screen.dispose()
    screen.deleteLater()


def test_quick_connect_wake_on_lan_sends_off_the_gui_thread(boxes, monkeypatch, tmp_path):
    from je_auto_control.gui.remote_desktop import connection_recent
    screen = _quick_connect(monkeypatch, tmp_path)
    gate = _Gate()
    monkeypatch.setattr(connection_recent, "send_magic_packet", gate)
    entry = {"host_id": "h", "server_url": "h", "mac_address": "aa:bb:cc:dd:ee:ff"}
    _returns_at_once(screen._send_wake_on_lan, entry, "h")
    assert gate.entered.wait(_WAIT)
    assert boxes == []
    gate.release.set()
    assert pump_until(lambda: len(boxes) == 1)
    assert gate.off_gui_thread()
    assert boxes == [_t("rd_quick_wol_sent").replace("{mac}", "aa:bb:cc:dd:ee:ff")]
    screen.dispose()
    screen.deleteLater()
