"""A cancelled email poll stops before the next trigger's server; the tab's Stop cancels a Poll Now.

Poll Now ran on a bare worker: with several mailboxes, each allowed 30 s per
IMAP step, Stop and closing the tab could not end it. The pass now checks its
cancellation scope between triggers -- never inside one, so a message is not
marked seen without its script having fired.
"""
import os
import threading
from concurrent.futures import CancelledError

import pytest

from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.triggers import email_trigger as et

_FAKE_PW = "p"  # never sent anywhere: _poll_one is replaced below


@pytest.fixture
def watcher(tmp_path):
    script = tmp_path / "s.json"
    script.write_text('[["AC_screen_size"]]', encoding="utf-8")
    w = et.EmailTriggerWatcher(executor=lambda actions, variables: None)
    for host in ("imap.one.example", "imap.two.example"):
        w.add(host=host, username="u", password=_FAKE_PW, script_path=str(script))
    yield w
    w.stop()


def test_a_poll_cancelled_during_one_trigger_does_not_reach_the_next(watcher, monkeypatch):
    token = CancellationToken(task_id=1)
    polled = []

    def poll_one(trigger):
        polled.append(trigger.host)
        token.cancel()              # Stop pressed while this mailbox was being read
        return 1

    monkeypatch.setattr(watcher, "_poll_one", poll_one)
    with cancellation_scope(token), pytest.raises(CancelledError):
        watcher.poll_once()
    assert polled == ["imap.one.example"]


def test_an_unscoped_poll_reads_every_trigger(watcher, monkeypatch):
    polled = []
    monkeypatch.setattr(watcher, "_poll_one", lambda trigger: polled.append(trigger.host) or 1)
    assert watcher.poll_once() == 2
    assert polled == ["imap.one.example", "imap.two.example"]


def test_the_tabs_stop_cancels_a_poll_now_in_flight(watcher, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from je_auto_control.gui import email_triggers_tab
    from headless._qt_settle import pump_until

    entered, release, polled, shown = threading.Event(), threading.Event(), [], []

    def poll_one(trigger):
        polled.append(trigger.host)
        entered.set()
        release.wait(10.0)
        return 1

    monkeypatch.setattr(watcher, "_poll_one", poll_one)
    monkeypatch.setattr(email_triggers_tab, "default_email_trigger_watcher", watcher)
    for name in ("information", "warning"):
        monkeypatch.setattr(email_triggers_tab.QMessageBox, name, lambda *args: shown.append(args[-1]))
    tab = email_triggers_tab.EmailTriggersTab()
    try:
        tab._on_poll_now()
        assert entered.wait(10.0)
        tab._on_stop()
        assert not tab._polls.running
        release.set()
        assert pump_until(lambda: not tab._watcher_op.busy)          # the watcher Stop went through too
        assert pump_until(lambda: bool(shown), timeout=0.5) is False   # no "Fired n" for a stopped poll
        assert polled == ["imap.one.example"]
    finally:
        release.set()
        tab.deleteLater()
