"""The Remote Desktop host tab passes its admission settings to the host it starts.

Offscreen Qt with a fake host class: no socket is opened, nothing is shown
and the screen is never read.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from je_auto_control.gui.remote_desktop import host_panel  # noqa: E402
from je_auto_control.utils.remote_desktop import host_admission  # noqa: E402
from je_auto_control.utils.remote_desktop.registry import registry  # noqa: E402
from headless._qt_settle import deleting, settle_op  # noqa: E402


class _Host:
    port, connected_clients, host_id = 4321, 0, "123456789"

    def __init__(self, **kwargs):
        self.kwargs, self.is_running = kwargs, False

    def start(self):
        self.is_running = True

    def stop(self, timeout=2.0):
        self.is_running = False

    def latest_frame(self):
        return None


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    QApplication.instance() or QApplication([])
    for box in ("warning", "information", "question", "critical"):
        monkeypatch.setattr(QMessageBox, box, lambda *args: None)
    for attr in ("_host", "_viewer", "_ws_host", "_ws_viewer"):
        monkeypatch.setattr(registry, attr, None)
    monkeypatch.setattr(registry, "_claims", {})
    monkeypatch.setattr(host_panel, "RemoteDesktopHost", _Host)
    monkeypatch.setattr(host_panel, "WebSocketDesktopHost", _Host)
    monkeypatch.setattr(host_panel, "is_audio_backend_available", lambda: False)
    with deleting(host_panel._HostPanel):
        yield


def _start(panel):
    panel._token.setText("tok")
    panel._start()
    assert settle_op(panel._host_op)
    return registry.host.kwargs


def test_the_fields_default_to_the_hosts_defaults():
    panel = host_panel._HostPanel()
    kwargs = _start(panel)
    assert kwargs["max_pending_handshakes"] == host_admission.DEFAULT_MAX_PENDING_HANDSHAKES
    assert kwargs["auth_timeout"] == host_admission.DEFAULT_AUTH_TIMEOUT_S


@pytest.mark.parametrize("transport", ["TCP", "WebSocket"])
def test_the_host_is_started_with_the_settings_entered(transport):
    panel = host_panel._HostPanel()
    panel._transport.setCurrentText(transport)
    panel._max_pending.setValue(3)
    panel._auth_timeout.setValue(4.5)
    kwargs = _start(panel)
    assert (kwargs["max_pending_handshakes"], kwargs["auth_timeout"]) == (3, 4.5)


def test_the_fields_stay_inside_what_the_host_accepts():
    panel = host_panel._HostPanel()
    assert panel._max_pending.minimum() >= 1
    assert 0 < panel._auth_timeout.minimum() <= panel._auth_timeout.maximum() <= 60
    for value in (panel._max_pending.minimum(), panel._max_pending.maximum()):
        host_admission.validate_admission_args(value, panel._auth_timeout.maximum())
