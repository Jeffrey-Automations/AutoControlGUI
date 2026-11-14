"""The USB passthrough panel's use requests: a Stop, a deadline, and no late answer.

List shared, Open and the remote REST fetch ran on one bare worker: no Stop,
no deadline, and a request made while another was out was silently ignored. A
WebRTC peer that stopped answering held the panel until its own timeout. They
now run as one :class:`~je_auto_control.gui._tab_task.TabTask`.
"""
import os
import threading

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
panel_mod = pytest.importorskip("je_auto_control.gui.usb_passthrough_panel",
                                reason="gui stack (webrtc extra) not importable")

from PySide6.QtWidgets import QApplication  # noqa: E402

from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402
from je_auto_control.utils.usb.passthrough import UsbAcl  # noqa: E402
from headless._qt_settle import pump_until  # noqa: E402

_APP = QApplication.instance() or QApplication([])
_DEVICE = {"vendor_id": "1050", "product_id": "0407", "product": "Key", "serial": "S1"}


def _t(key):
    return language_wrapper.translate(key, key)


class _Handle:
    def control_transfer(self, **_kwargs):
        return b"\x12\x01\x00\x02"

    def close(self):
        pass


class _SlowClient:
    """A remote USB client that answers once ``release`` is set."""

    def __init__(self):
        self.release, self.asked = threading.Event(), threading.Event()

    def list_devices(self):
        self.asked.set()
        self.release.wait(30.0)
        return [_DEVICE]

    def open(self, **_kwargs):
        self.asked.set()
        self.release.wait(30.0)
        return _Handle()


@pytest.fixture
def remote(tmp_path):
    client = _SlowClient()
    panel = panel_mod.UsbPassthroughPanel(acl=UsbAcl(path=tmp_path / "acl.json"),
                                          remote_client_provider=lambda: client)
    panel._source_combo.setCurrentIndex(1)              # Remote (WebRTC)
    yield panel, client
    client.release.set()
    panel.deleteLater()


def _menu(panel, key):
    return dict(panel.menu_actions())[key]


def test_stop_drops_a_listing_still_out(remote):
    panel, client = remote
    _menu(panel, "usb_share_fetch_shared")()
    assert client.asked.wait(10.0)
    _menu(panel, "task_stop")()
    assert panel._viewer_status.text() == _t("task_stopped")
    assert not panel._requests.running
    client.release.set()
    assert pump_until(lambda: panel._shared_table.rowCount() != 0, timeout=0.5) is False
    assert panel._viewer_status.text() == _t("task_stopped")


def test_an_open_past_its_deadline_says_so(remote, monkeypatch):
    panel, client = remote
    monkeypatch.setattr(panel_mod, "REQUEST_DEADLINE_S", 0.05)
    client.release.set()
    _menu(panel, "usb_share_fetch_shared")()
    assert pump_until(lambda: panel._shared_table.rowCount() == 1)
    client.release.clear()
    panel._shared_table.selectRow(0)
    _menu(panel, "usb_share_open_selected")()
    assert pump_until(lambda: panel._viewer_status.text() == _t("task_timed_out"))


def test_a_second_request_while_one_is_out_is_refused_visibly(remote):
    panel, client = remote
    _menu(panel, "usb_share_fetch_shared")()
    assert client.asked.wait(10.0)
    _menu(panel, "usb_share_remote_fetch")()
    assert panel._viewer_status.text() == _t("task_busy")


def test_a_finished_open_shows_the_descriptor(remote):
    panel, client = remote
    client.release.set()
    _menu(panel, "usb_share_fetch_shared")()
    assert pump_until(lambda: panel._shared_table.rowCount() == 1)
    panel._shared_table.selectRow(0)
    _menu(panel, "usb_share_open_selected")()
    assert pump_until(lambda: panel._viewer_status.text().startswith(
        _t("usb_share_opened").split("{", 1)[0]))
    assert "1050" in panel._viewer_status.text()


def test_a_failed_remote_fetch_shows_the_fetch_error(remote, monkeypatch):
    panel, _client = remote

    def fetch(**_kwargs):
        raise ValueError("unexpected response shape")

    monkeypatch.setattr(panel_mod, "fetch_remote_devices", fetch)
    _menu(panel, "usb_share_remote_fetch")()
    assert pump_until(lambda: panel._viewer_status.text() == _t("usb_browser_fetch_failed").format(
        error="unexpected response shape"))


def test_disposing_the_panel_drops_the_answer(remote):
    panel, client = remote
    _menu(panel, "usb_share_fetch_shared")()
    assert client.asked.wait(10.0)
    panel.dispose()
    assert not panel._requests.running
    client.release.set()
    assert pump_until(lambda: panel._shared_table.rowCount() != 0, timeout=0.5) is False
