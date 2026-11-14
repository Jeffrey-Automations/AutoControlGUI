"""The admin console's health poll and thumbnail fetch stop at the hosts not reached yet.

Both probed every host, ``max_parallel`` at a time with 3 s per request, on
bare workers: closing the tab or wanting the poll to end left it to finish
every host. They now observe the caller's cancellation scope, and the tab runs
them as cancellable tasks with **Stop polling** and a deadline.
"""
import os
import threading
from concurrent.futures import CancelledError

import pytest

from je_auto_control.utils.admin.admin_client import AdminConsoleClient
from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope

_HOSTS = ("alpha", "beta", "gamma")


@pytest.fixture
def console(tmp_path):
    client = AdminConsoleClient(persist_path=tmp_path / "hosts.json", max_parallel=1)
    for label in _HOSTS:
        # No network: the HTTP call is faked.
        client.add_host(label, f"http://{label}.example", "tok")  # NOSONAR python:S5332
    return client


def _fake_get(console, monkeypatch, on_get=None):
    asked = []

    def get(host, path):
        asked.append((host.label, path))
        if on_get is not None:
            on_get(host)
        return {"sessions": []} if path == "/sessions" else {"jobs": []}

    monkeypatch.setattr(console, "_http_get", get)
    return asked


def _hosts(asked):
    return sorted({label for label, _path in asked})


def test_an_unscoped_poll_reaches_every_host(console, monkeypatch):
    asked = _fake_get(console, monkeypatch)
    statuses = console.poll_all()
    assert [status.label for status in statuses] == list(_HOSTS)
    assert _hosts(asked) == list(_HOSTS)


def test_a_poll_cancelled_during_the_first_host_skips_the_rest(console, monkeypatch):
    token = CancellationToken(task_id=1)
    asked = _fake_get(console, monkeypatch, on_get=lambda host: token.cancel())
    with cancellation_scope(token), pytest.raises(CancelledError):
        console.poll_all()
    assert _hosts(asked) == ["alpha"]


def test_a_thumbnail_round_cancelled_during_the_first_host_skips_the_rest(console, monkeypatch):
    token = CancellationToken(task_id=2)
    asked = _fake_get(console, monkeypatch, on_get=lambda host: token.cancel())
    with cancellation_scope(token), pytest.raises(CancelledError):
        console.fetch_thumbnails()
    assert asked == [("alpha", "/screenshot")]


def test_an_unscoped_thumbnail_round_reaches_every_host(console, monkeypatch):
    asked = _fake_get(console, monkeypatch)
    assert console.fetch_thumbnails() == {label: None for label in _HOSTS}
    assert [label for label, _path in asked] == list(_HOSTS)


@pytest.fixture
def held_tab(console, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from je_auto_control.gui import admin_console_tab

    entered, release = threading.Event(), threading.Event()

    def hold(host):
        entered.set()
        release.wait(10.0)

    asked = _fake_get(console, monkeypatch, on_get=hold)
    monkeypatch.setattr(admin_console_tab, "default_admin_console", lambda: console)
    warnings = []
    monkeypatch.setattr(admin_console_tab.QMessageBox, "warning", lambda *args: warnings.append(args))
    tab = admin_console_tab.AdminConsoleTab()
    tab._thumb_timer.stop()
    yield tab, asked, entered, release, warnings
    release.set()
    tab.deleteLater()


def test_stop_polling_ends_the_poll_at_the_host_in_flight(held_tab):
    from headless._qt_settle import pump_until
    tab, asked, entered, release, warnings = held_tab
    actions = dict(tab.menu_actions())
    actions["admin_refresh"]()
    assert entered.wait(10.0)
    actions["admin_poll_stop"]()
    assert not tab._polls.running
    release.set()
    assert pump_until(lambda: len(_hosts(asked)) > 1, timeout=0.5) is False
    assert _hosts(asked) == ["alpha"]
    assert warnings == []                   # a stopped poll is not a failure


def test_closing_the_tab_ends_the_thumbnail_round(held_tab):
    from headless._qt_settle import pump_until
    tab, asked, entered, release, _warnings = held_tab
    tab._refresh_thumbnails()
    assert entered.wait(10.0)
    tab.dispose()
    assert not tab._thumbs.running
    release.set()
    assert pump_until(lambda: len(asked) > 1, timeout=0.5) is False
    assert asked == [("alpha", "/screenshot")]


def test_a_poll_past_its_deadline_says_so(held_tab, monkeypatch):
    from headless._qt_settle import pump_until
    from je_auto_control.gui import admin_console_tab
    from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
    tab, _asked, _entered, _release, warnings = held_tab
    monkeypatch.setattr(admin_console_tab, "POLL_DEADLINE_S", 0.05)
    tab._on_refresh()
    assert pump_until(lambda: bool(warnings))
    assert warnings[0][-1] == language_wrapper.translate("task_timed_out", "task_timed_out")
