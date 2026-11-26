"""TLS material, trust-list writes, audit queries and template crops no longer hold the GUI thread.

Offscreen Qt against fakes: each blocking call -- reading the CA store or a
certificate chain, recording a trusted viewer, querying the audit database,
grabbing the screen for a template -- is replaced by one that waits on a gate,
so the test sees the slot return first and the outcome arrive later, on the
GUI thread. No dialog is executed, no window shown and no screen read.
"""
import os
import ssl
import threading
import time
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from headless._qt_settle import deleting, pump_until, settle, settle_op  # noqa: E402
from je_auto_control.gui.remote_desktop import connection_screen, host_panel, viewer_panel  # noqa: E402
from je_auto_control.utils.remote_desktop.connect_coordinator import parse_target  # noqa: E402
from je_auto_control.utils.remote_desktop.registry import registry  # noqa: E402

_WAIT = 10.0


@pytest.fixture(autouse=True)
def qapp(monkeypatch):
    app = QApplication.instance() or QApplication([])
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: warnings.append(args[-1]))
    monkeypatch.setattr(registry, "_viewer", None)
    monkeypatch.setattr(registry, "_ws_viewer", None)
    monkeypatch.setattr(registry, "_host", None)
    app.warnings = warnings
    with deleting(connection_screen.QuickConnectScreen, viewer_panel._ViewerPanel, host_panel._HostPanel):
        yield app


class _Gate:
    """A blocking call that waits until released, remembers where it ran, then returns or raises."""

    def __init__(self, result=None, error=None, order=None) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.threads: list = []
        self.result, self.error, self.order = result, error, order

    def __call__(self, *args, **kwargs):
        self.threads.append(threading.get_ident())
        if self.order is not None:
            self.order.append("gate")
        self.entered.set()
        self.release.wait(_WAIT)
        if self.error is not None:
            raise self.error
        return self.result

    def off_gui_thread(self) -> bool:
        return bool(self.threads) and all(ident != threading.get_ident() for ident in self.threads)


def _returns_at_once(slot, *args) -> None:
    started = time.monotonic()
    slot(*args)
    assert time.monotonic() - started < 5.0, "the slot held the GUI thread"


class _Viewer:
    """A viewer that records its TLS context and when it was asked to connect."""

    connected = False
    remote_host_id = None

    def __init__(self, order, **kwargs) -> None:
        self.order, self.kwargs = order, kwargs

    def set_file_receiver(self, _receiver) -> None:
        return None

    def connect(self, timeout) -> None:
        self.order.append("connect")
        raise OSError("refused")

    def disconnect(self, *args, **kwargs) -> None:
        return None


# --- the CA store a verifying client context reads ------------------------------------------------------------

def _tls_viewer_panel(monkeypatch, order):
    monkeypatch.setattr(viewer_panel, "RemoteDesktopViewer",
                        lambda **kwargs: _Viewer(order, **kwargs))
    panel = viewer_panel._ViewerPanel()
    panel._host_field.setText("desk")
    panel._port.setValue(5555)
    panel._token.setText("tok")
    panel._transport.setCurrentText("TLS")
    panel._tls_insecure.setChecked(False)
    return panel


def test_the_viewer_loads_the_ca_store_on_the_connect_worker(qapp, monkeypatch):
    order = []
    gate = _Gate(order=order)
    monkeypatch.setattr(ssl.SSLContext, "load_default_certs", gate)
    panel = _tls_viewer_panel(monkeypatch, order)
    _returns_at_once(panel._connect)
    assert gate.entered.wait(_WAIT)
    gate.release.set()
    assert settle(panel)
    assert gate.off_gui_thread()
    assert order == ["gate", "connect"]                 # trusted before it dials
    assert qapp.warnings == ["refused"]
    panel.dispose()


def test_a_ca_store_that_does_not_load_is_the_connects_error(qapp, monkeypatch):
    order = []
    gate = _Gate(error=ssl.SSLError("no CA store"), order=order)
    monkeypatch.setattr(ssl.SSLContext, "load_default_certs", gate)
    panel = _tls_viewer_panel(monkeypatch, order)
    panel._connect()
    gate.release.set()
    assert settle(panel)
    assert order == ["gate"]                            # never dialled
    assert len(qapp.warnings) == 1 and "no CA store" in qapp.warnings[0]
    panel.dispose()


def test_an_insecure_viewer_context_loads_nothing(qapp, monkeypatch):
    order = []
    gate = _Gate(order=order)
    monkeypatch.setattr(ssl.SSLContext, "load_default_certs", gate)
    panel = _tls_viewer_panel(monkeypatch, order)
    panel._tls_insecure.setChecked(True)
    panel._connect()
    assert settle(panel)
    assert order == ["connect"]
    panel.dispose()


def test_quick_connect_loads_the_wss_ca_store_on_the_connect_worker(qapp, monkeypatch):
    order = []
    gate = _Gate(order=order)
    monkeypatch.setattr(ssl.SSLContext, "load_default_certs", gate)
    monkeypatch.setattr(connection_screen, "WebSocketDesktopViewer", lambda **kwargs: _Viewer(order, **kwargs))
    screen = connection_screen.QuickConnectScreen()
    _returns_at_once(screen._dispatch_target, parse_target("wss://desk:8443/"), "tok")
    assert gate.entered.wait(_WAIT)
    gate.release.set()
    assert settle(screen)
    assert gate.off_gui_thread()
    assert order == ["gate", "connect"]
    assert qapp.warnings == ["refused"]
    screen.dispose()


# --- the certificate chain a TLS host serves ------------------------------------------------------------------

class _Host:
    is_running, port, connected_clients, host_id = True, 4321, 0, "123456789"

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.stopped = False

    def start(self) -> None:
        return None

    def stop(self, *args, **kwargs) -> None:
        self.stopped = True

    def latest_frame(self):
        return None


def _tls_host_panel(monkeypatch):
    monkeypatch.setattr(host_panel, "RemoteDesktopHost", _Host)
    panel = host_panel._HostPanel()
    panel._token.setText("tok")
    panel._tls_cert.setText("host.crt")
    panel._tls_key.setText("host.key")
    return panel


def test_the_host_reads_its_certificate_chain_on_the_start_worker(qapp, monkeypatch):
    gate = _Gate()
    monkeypatch.setattr(ssl.SSLContext, "load_cert_chain", gate)
    panel = _tls_host_panel(monkeypatch)
    _returns_at_once(panel._start)
    assert gate.entered.wait(_WAIT)
    assert panel._host_op.busy                          # the badge says starting meanwhile
    gate.release.set()
    assert settle_op(panel._host_op)
    assert gate.off_gui_thread()
    assert isinstance(registry.host.kwargs["ssl_context"], ssl.SSLContext)
    assert panel._shared["transport"] == "TLS"
    assert qapp.warnings == []
    registry.release("host", panel._owner)
    panel.dispose()


def test_a_certificate_that_does_not_load_stops_nothing_and_is_shown(qapp, monkeypatch):
    gate = _Gate(error=ssl.SSLError("bad key"))
    gate.release.set()
    monkeypatch.setattr(ssl.SSLContext, "load_cert_chain", gate)
    running = _Host()
    monkeypatch.setattr(registry, "_host", running)
    panel = _tls_host_panel(monkeypatch)
    panel._shared = {"host": running, "transport": "TCP"}
    panel._start()
    panel._start()                                      # a second click while the first is out is ignored
    assert settle_op(panel._host_op)
    assert registry.host is running and not running.stopped
    assert panel._shared == {"host": running, "transport": "TCP"}
    assert len(qapp.warnings) == 1 and "bad key" in qapp.warnings[0]
    panel.dispose()


def test_only_one_of_certificate_and_key_is_refused_before_anything_runs(qapp, monkeypatch):
    gate = _Gate()
    monkeypatch.setattr(ssl.SSLContext, "load_cert_chain", gate)
    panel = _tls_host_panel(monkeypatch)
    panel._tls_key.setText("")
    panel._start()
    assert not panel._host_op.busy
    assert not gate.threads
    assert len(qapp.warnings) == 1
    panel.dispose()


# --- accept and trust a pending WebRTC viewer -----------------------------------------------------------------

def _trusting_panel(monkeypatch, gate):
    pytest.importorskip("av")
    pytest.importorskip("aiortc")
    from je_auto_control.gui.remote_desktop import webrtc_panel

    class Dialog:
        AcceptAndTrust, AcceptOnce = 2, 1

        def __init__(self, *args, **kwargs):
            return None

        def exec(self):
            return None

        def choice(self):
            return Dialog.AcceptAndTrust

    monkeypatch.setattr(webrtc_panel, "PendingViewerDialog", Dialog)
    panel = webrtc_panel._WebRTCHostPanel()
    panel._multi_host = types.SimpleNamespace(trust_pending_viewer=gate, session_count=lambda: 1)
    counts = []
    panel._signals.session_count.connect(counts.append)
    return panel, counts


def test_accept_and_trust_records_the_viewer_off_the_gui_thread(qapp, monkeypatch):
    gate = _Gate()
    panel, counts = _trusting_panel(monkeypatch, gate)
    _returns_at_once(panel._on_pending_viewer, "session-1", "viewer")
    assert gate.entered.wait(_WAIT)
    assert not panel._trusted_list.isEnabled()          # disabled until the call returns
    assert counts == []
    gate.release.set()
    assert pump_until(panel._trusted_list.isEnabled)
    assert gate.off_gui_thread()
    assert counts == [1]
    panel.deleteLater()


def test_a_session_gone_before_the_trust_was_recorded_is_not_an_error(qapp, monkeypatch):
    gate = _Gate(error=KeyError("session-1"))
    panel, counts = _trusting_panel(monkeypatch, gate)
    panel._on_pending_viewer("session-1", "viewer")
    gate.release.set()
    assert pump_until(panel._trusted_list.isEnabled)
    assert counts == []
    assert qapp.warnings == []
    panel.deleteLater()


# --- the audit log dialog -------------------------------------------------------------------------------------

class _AuditLog:
    def __init__(self, gate) -> None:
        self.gate = gate
        self.asked: list = []

    def query(self, **kwargs):
        self.asked.append(kwargs)
        return self.gate()


_ROW = {"ts": "2026-11-26T10:00:00+00:00", "event_type": "auth_ok", "host_id": "h", "viewer_id": "v",
        "detail": "remote_ip=127.0.0.1"}


def test_the_audit_log_is_opened_and_queried_off_the_gui_thread(qapp):
    from je_auto_control.gui.remote_desktop.webrtc_dialogs import AuditLogDialog
    gate = _Gate(result=[_ROW])
    log = _AuditLog(gate)
    opened = []

    def open_log():
        opened.append(threading.get_ident())
        return log

    started = time.monotonic()
    dialog = AuditLogDialog(open_log)
    assert time.monotonic() - started < 5.0, "the dialog held the GUI thread"
    assert gate.entered.wait(_WAIT)
    assert not dialog._refresh_btn.isEnabled()
    assert dialog._status.text()                        # the loading text
    gate.release.set()
    assert pump_until(lambda: dialog._table.rowCount() == 1)
    assert pump_until(dialog._refresh_btn.isEnabled)
    assert dialog._table.item(0, 1).text() == "auth_ok"
    assert dialog._status.text() == ""
    assert opened and opened[0] != threading.get_ident()
    assert gate.off_gui_thread()
    assert log.asked == [{"event_type": None, "host_id": None, "limit": 500}]
    dialog.deleteLater()


def test_an_audit_query_that_fails_is_shown_in_the_dialog(qapp):
    from je_auto_control.gui.remote_desktop.webrtc_dialogs import AuditLogDialog
    from je_auto_control.utils.remote_desktop.audit_log import AuditLogError
    gate = _Gate(error=AuditLogError("database is locked"))
    gate.release.set()
    dialog = AuditLogDialog(_AuditLog(gate))
    assert pump_until(lambda: "locked" in dialog._status.text())
    assert pump_until(dialog._refresh_btn.isEnabled)
    assert dialog._table.rowCount() == 0
    dialog.deleteLater()


def test_closing_the_audit_dialog_drops_the_query_still_out(qapp):
    from je_auto_control.gui.remote_desktop.webrtc_dialogs import AuditLogDialog
    gate = _Gate(result=[_ROW])
    dialog = AuditLogDialog(_AuditLog(gate))
    assert gate.entered.wait(_WAIT)
    dialog.done(0)
    gate.release.set()
    assert pump_until(lambda: not dialog._task.running)
    time.sleep(0.05)
    qapp.processEvents()
    assert dialog._table.rowCount() == 0
    dialog.deleteLater()


# --- the image detection tab's template crop ------------------------------------------------------------------

def _crop_tab(monkeypatch, tmp_path, gate):
    import numpy as np
    from je_auto_control.gui import _image_detect_tab as module
    from je_auto_control.gui.selector import region_selector, template_cropper
    target = tmp_path / "template.png"
    picked = []
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName", lambda *args: (str(target), "PNG"))
    monkeypatch.setattr(region_selector, "pick_region_blocking",
                        lambda *_args: picked.append(threading.get_ident()) or (1, 2, 4, 4))
    gate.result = np.zeros((4, 4, 3), np.uint8)
    monkeypatch.setattr(template_cropper, "_capture_region", gate)
    return module.ImageDetectionTab(), target, picked


def test_the_template_is_grabbed_and_written_off_the_gui_thread(qapp, monkeypatch, tmp_path):
    gate = _Gate()
    tab, target, picked = _crop_tab(monkeypatch, tmp_path, gate)
    _returns_at_once(tab._crop_template)
    assert gate.entered.wait(_WAIT)
    assert picked == [threading.get_ident()]            # the region is picked on the GUI thread
    assert tab._task.running
    assert tab.img_path_input.text() == ""
    gate.release.set()
    assert pump_until(lambda: not tab._task.running)
    assert gate.off_gui_thread()
    assert target.is_file()
    assert tab.img_path_input.text() == str(target)
    assert "Template saved" in tab.detect_result_text.toPlainText()
    tab.dispose()
    tab.deleteLater()


def test_a_template_grab_that_fails_is_shown_in_the_tab(qapp, monkeypatch, tmp_path):
    gate = _Gate(error=OSError("no screen to grab"))
    tab, target, _picked = _crop_tab(monkeypatch, tmp_path, gate)
    gate.release.set()
    tab._crop_template()
    assert pump_until(lambda: not tab._task.running)
    assert not target.exists()
    assert tab.img_path_input.text() == ""
    assert "no screen to grab" in tab.detect_result_text.toPlainText()
    tab.dispose()
    tab.deleteLater()


def test_dispose_drops_the_crop_still_out(qapp, monkeypatch, tmp_path):
    gate = _Gate()
    tab, _target, _picked = _crop_tab(monkeypatch, tmp_path, gate)
    tab._crop_template()
    assert gate.entered.wait(_WAIT)
    tab.dispose()
    gate.release.set()
    assert pump_until(lambda: not tab._task.running)
    time.sleep(0.05)
    qapp.processEvents()
    assert tab.img_path_input.text() == ""
    tab.deleteLater()
