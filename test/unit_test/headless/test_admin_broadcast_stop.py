"""A stopped admin broadcast reports, host by host, whether the actions were sent.

A broadcast runs actions on many machines. Stopping it used to be impossible;
now hosts not sent to yet are skipped and every host still gets a row whose
``sent`` says which happened, so the operator knows where the actions ran.
"""
import os
import threading

import pytest

from je_auto_control.utils.admin.admin_client import NOT_SENT_STOPPED, AdminConsoleClient
from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope

_HOSTS = ("alpha", "beta", "gamma")


@pytest.fixture
def console(tmp_path):
    # One host at a time, so "not reached yet" is well defined.
    client = AdminConsoleClient(persist_path=tmp_path / "hosts.json", max_parallel=1)
    for label in _HOSTS:
        # No network: the HTTP call is faked.
        client.add_host(label, f"http://{label}.example", "tok")  # NOSONAR python:S5332
    return client


def _fake_post(console, monkeypatch, on_post=None):
    posted = []

    def post(host, path, body):
        posted.append(host.label)
        if on_post is not None:
            on_post(host)
        return {"result": {"host": host.label}}

    monkeypatch.setattr(console, "_http_post", post)
    return posted


def test_every_row_of_a_finished_broadcast_was_sent(console, monkeypatch):
    posted = _fake_post(console, monkeypatch)
    rows = console.broadcast_execute([["AC_x"]])
    assert [(row["label"], row["ok"], row["sent"]) for row in rows] == [(label, True, True) for label in _HOSTS]
    assert posted == list(_HOSTS)


def test_a_stop_during_the_first_host_skips_the_rest_and_says_so(console, monkeypatch):
    stop = threading.Event()
    posted = _fake_post(console, monkeypatch, on_post=lambda host: stop.set())
    rows = console.broadcast_execute([["AC_x"]], stop_event=stop)
    assert posted == ["alpha"]
    assert rows[0] == {"label": "alpha", "ok": True, "sent": True, "result": {"result": {"host": "alpha"}}}
    assert rows[1:] == [{"label": label, "ok": False, "sent": False, "error": NOT_SENT_STOPPED}
                        for label in ("beta", "gamma")]


def test_a_broadcast_stopped_before_it_starts_sends_nothing(console, monkeypatch):
    stop = threading.Event()
    stop.set()
    posted = _fake_post(console, monkeypatch)
    rows = console.broadcast_execute([["AC_x"]], stop_event=stop)
    assert posted == []
    assert all(row["sent"] is False and row["error"] == NOT_SENT_STOPPED for row in rows)


def test_a_cancelled_scope_stops_the_broadcast_the_same_way(console, monkeypatch):
    token = CancellationToken(task_id=1)
    posted = _fake_post(console, monkeypatch, on_post=lambda host: token.cancel())
    with cancellation_scope(token):
        rows = console.broadcast_execute([["AC_x"]])
    assert posted == ["alpha"]
    assert [row["sent"] for row in rows] == [True, False, False]


def test_a_host_that_failed_was_still_sent_to(console, monkeypatch):
    monkeypatch.setattr(console, "_http_post", lambda host, path, body: {"ok": False, "error": "boom"})
    rows = console.broadcast_execute([["AC_x"]], labels=["alpha", "typo"])
    assert rows == [
        {"label": "alpha", "ok": False, "sent": True, "error": "boom", "result": {"ok": False, "error": "boom"}},
        {"label": "typo", "ok": False, "sent": False, "error": "unknown host"},
    ]


def test_the_tabs_stop_shows_which_hosts_were_sent_to(console, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import json
    from je_auto_control.gui import admin_console_tab
    from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
    from headless._qt_settle import pump_until

    entered, release = threading.Event(), threading.Event()

    def hold(host):
        entered.set()
        release.wait(10.0)

    posted = _fake_post(console, monkeypatch, on_post=hold)
    monkeypatch.setattr(admin_console_tab, "default_admin_console", lambda: console)
    monkeypatch.setattr(console, "fetch_thumbnails", lambda *a, **k: {})
    tab = admin_console_tab.AdminConsoleTab()
    try:
        tab._thumb_timer.stop()
        tab._actions_input.setPlainText('[["AC_x"]]')
        actions = dict(tab.menu_actions())
        actions["admin_broadcast_run"]()
        assert entered.wait(10.0)
        actions["admin_broadcast_stop"]()
        assert tab._broadcast_status.text() == language_wrapper.translate(
            "admin_broadcast_stopping", "admin_broadcast_stopping")
        release.set()
        assert pump_until(lambda: tab._broadcast_output.toPlainText() != "")
        rows = json.loads(tab._broadcast_output.toPlainText())
        assert [(row["label"], row["sent"]) for row in rows] == [("alpha", True), ("beta", False), ("gamma", False)]
        assert posted == ["alpha"]
        assert tab._broadcast_status.text() == language_wrapper.translate(
            "admin_broadcast_summary", "admin_broadcast_summary").format(sent=1, total=3, skipped=2)
    finally:
        release.set()
        tab.deleteLater()
