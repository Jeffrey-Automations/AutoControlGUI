"""The USB Browser's fetch and local open: a Stop, a deadline, and no late answer.

Both ran on bare workers with no Stop: a host that accepted the connection and
then said nothing held the tab's Fetch for the whole HTTP timeout, and a second
Fetch was silently ignored. They now run as one
:class:`~je_auto_control.gui._tab_task.TabTask`.
"""
import os
import threading

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from je_auto_control.gui import usb_browser_tab  # noqa: E402
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402
from headless._qt_settle import pump_until  # noqa: E402

_APP = QApplication.instance() or QApplication([])
_DEVICE = {"vendor_id": "046d", "product_id": "c52b", "product": "Receiver"}


def _t(key):
    return language_wrapper.translate(key, key)


@pytest.fixture
def slow_fetch(monkeypatch):
    release, asked = threading.Event(), threading.Event()

    def fetch(*, base_url, token, timeout_s=5.0):
        asked.set()
        release.wait(30.0)
        return [_DEVICE]

    monkeypatch.setattr(usb_browser_tab, "fetch_remote_devices", fetch)
    tab = usb_browser_tab.UsbBrowserTab()
    yield tab, release, asked
    release.set()
    tab.deleteLater()


def _menu(tab, key):
    return dict(tab.menu_actions())[key]


def test_stop_drops_a_fetch_still_out(slow_fetch):
    tab, release, asked = slow_fetch
    _menu(tab, "usb_browser_fetch")()
    assert asked.wait(10.0)
    _menu(tab, "task_stop")()
    assert tab._status_label.text() == _t("task_stopped")
    assert not tab._requests.running            # a new Fetch can start at once
    release.set()
    assert pump_until(lambda: tab._table.rowCount() != 0, timeout=0.5) is False
    assert tab._status_label.text() == _t("task_stopped")


def test_a_fetch_past_its_deadline_says_so(slow_fetch, monkeypatch):
    tab, _release, _asked = slow_fetch
    monkeypatch.setattr(usb_browser_tab, "REQUEST_DEADLINE_S", 0.05)
    _menu(tab, "usb_browser_fetch")()
    assert pump_until(lambda: tab._status_label.text() == _t("task_timed_out"))
    assert tab._table.rowCount() == 0


def test_a_second_request_while_one_is_out_is_refused_visibly(slow_fetch):
    tab, _release, asked = slow_fetch
    _menu(tab, "usb_browser_fetch")()
    assert asked.wait(10.0)
    tab._start_local_open("046d", "c52b", None)
    assert tab._status_label.text() == _t("task_busy")


def test_a_finished_fetch_fills_the_table(slow_fetch):
    tab, release, _asked = slow_fetch
    release.set()
    _menu(tab, "usb_browser_fetch")()
    assert pump_until(lambda: tab._table.rowCount() == 1)
    assert tab._table.item(0, 3).text() == "Receiver"
    assert tab._status_label.text() == _t("usb_browser_fetched").format(count=1)


def test_a_failed_fetch_shows_its_error(monkeypatch):
    def fetch(**_kwargs):
        raise ValueError("base_url is required")

    monkeypatch.setattr(usb_browser_tab, "fetch_remote_devices", fetch)
    tab = usb_browser_tab.UsbBrowserTab()
    try:
        _menu(tab, "usb_browser_fetch")()
        assert pump_until(lambda: tab._status_label.text() == _t("usb_browser_fetch_failed").format(
            error="base_url is required"))
    finally:
        tab.deleteLater()
