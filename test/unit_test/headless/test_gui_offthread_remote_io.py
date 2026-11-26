"""TLS material no longer holds the GUI thread.

Offscreen Qt against fakes: each blocking call -- reading the CA store or a
certificate chain -- is replaced by one that waits on a gate,
so the test sees the slot return first and the outcome arrive later, on the
GUI thread. No dialog is executed, no window shown and no screen read.
"""
import os
import ssl
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from headless._qt_settle import deleting, settle, settle_op  # noqa: E402
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
