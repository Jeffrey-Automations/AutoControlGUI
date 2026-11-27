"""Run the browser extension's scripts in the Qt JavaScript engine and drive them.

``test_browser_extension_scaffold.py`` reads the sources; this module executes
them, against the fake ``chrome.*`` / DOM in ``_extension_js_harness.py``.
"""
import json

import pytest

pytest.importorskip("PySide6.QtQml")

from headless._extension_js_harness import ExtensionHarness  # noqa: E402  # reason: after importorskip

_TAB = 7
_START = {"command": "start", "startUrl": "https://example.test/start", "tabId": _TAB}


@pytest.fixture()
def harness():
    """A fresh engine per test: each one starts with empty storage and no listeners."""
    yield ExtensionHarness()


@pytest.fixture()
def recorder(harness):
    """The background service worker, loaded."""
    harness.load_background()
    return harness


def _click(selector: str) -> dict:
    return {"command": "event", "event": {"type": "click", "selector": selector, "url": "https://example.test/"}}


# === Baseline ============================================================

def test_background_records_a_session_and_exports_it(recorder):
    assert recorder.request(_START) == {"ok": True}
    assert recorder.request(_click("#login"), _TAB) == {"ok": True}
    stopped = recorder.request({"command": "stop"})
    assert stopped["ok"] is True
    exported = json.loads(recorder.request({"command": "export"})["json"])
    assert exported == [
        ["AC_web_open", {"url": "https://example.test/start"}],
        ["AC_web_run", {"action": "WR_left_click", "params": {"element_name": "#login"}}],
    ]
    assert recorder.stored_state()["recording"] is False


def test_background_rejects_events_while_idle(recorder):
    assert recorder.request(_click("#login"), _TAB) == {"ok": False, "reason": "not recording"}


def test_content_script_announces_the_page_on_load(harness):
    harness.load_script("content_script.js")
    assert harness.value("__ext.outbox") == [
        {"command": "event", "event": {"type": "navigate", "url": "https://example.test/login"}},
    ]


# === R07: one write queue ================================================

def _finish_storage(harness) -> None:
    """Let reads finish as soon as they can and writes finish newest first, until storage is idle.

    That order is the one that loses work when two messages overlap: both read
    the same old state, and the older write lands last.
    """
    for _ in range(100):
        kinds = harness.pending()
        if not kinds:
            return
        harness.complete(kinds.index("get") if "get" in kinds else len(kinds) - 1)
    raise AssertionError("storage never went idle")


def _recorded_selectors(harness) -> list:
    return [action[1]["params"]["element_name"] for action in harness.stored_state()["actions"]
            if action[0] == "AC_web_run"]


def test_two_quick_events_are_both_kept(recorder):
    recorder.request(_START)
    recorder.manual_storage()
    first = recorder.send(_click("#first"), _TAB)
    second = recorder.send(_click("#second"), _TAB)
    _finish_storage(recorder)
    assert recorder.reply(first) == {"ok": True}
    assert recorder.reply(second) == {"ok": True}
    assert _recorded_selectors(recorder) == ["#first", "#second"]


def test_stop_wins_over_an_event_still_being_written(recorder):
    recorder.request(_START)
    recorder.manual_storage()
    early = recorder.send(_click("#early"), _TAB)
    stop = recorder.send({"command": "stop"})
    late = recorder.send(_click("#late"), _TAB)
    _finish_storage(recorder)
    assert recorder.reply(early) == {"ok": True}
    assert recorder.reply(stop)["ok"] is True
    assert recorder.reply(late) == {"ok": False, "reason": "not recording"}
    state = recorder.stored_state()
    assert state["recording"] is False
    assert _recorded_selectors(recorder) == ["#early"]


def test_reset_is_not_undone_by_an_event_queued_before_it(recorder):
    recorder.request(_START)
    recorder.manual_storage()
    recorder.send(_click("#before-reset"), _TAB)
    reset = recorder.send({"command": "reset"})
    _finish_storage(recorder)
    assert recorder.reply(reset) == {"ok": True}
    state = recorder.stored_state()
    assert state["recording"] is False
    assert state["actions"] == []


def test_start_after_stop_begins_a_new_recording(recorder):
    recorder.request(_START)
    recorder.manual_storage()
    recorder.send(_click("#old"), _TAB)
    recorder.send({"command": "stop"})
    recorder.send(_START)
    fresh = recorder.send(_click("#new"), _TAB)
    _finish_storage(recorder)
    assert recorder.reply(fresh) == {"ok": True}
    assert recorder.stored_state()["recording"] is True
    assert _recorded_selectors(recorder) == ["#new"]


# === R05: only the tab that started the recording =======================

_OTHER_TAB = 8


def _navigate(url: str) -> dict:
    return {"command": "event", "event": {"type": "navigate", "url": url}}


def test_popup_start_names_the_tab_it_records(harness):
    harness.load_script("popup.js")
    harness.run('__dom.click("start")')
    harness.drain()
    starts = [message for message in harness.value("__ext.outbox") if message["command"] == "start"]
    assert starts == [{"command": "start", "startUrl": "https://example.test/start", "tabId": 7}]


def test_events_from_another_tab_are_refused_while_interleaved(recorder):
    recorder.request(_START)
    replies = [
        recorder.request(_click("#mine-1"), _TAB),
        recorder.request(_click("#theirs-1"), _OTHER_TAB),
        recorder.request(_navigate("https://example.test/next"), _TAB),
        recorder.request(_navigate("https://elsewhere.test/"), _OTHER_TAB),
        recorder.request(_click("#mine-2"), _TAB),
        recorder.request(_click("#theirs-2"), _OTHER_TAB),
    ]
    refused = {"ok": False, "reason": "not the recording tab"}
    assert replies == [{"ok": True}, refused] * 3
    assert recorder.stored_state()["actions"] == [
        ["AC_web_open", {"url": "https://example.test/start"}],
        ["AC_web_run", {"action": "WR_left_click", "params": {"element_name": "#mine-1"}}],
        ["AC_web_open", {"url": "https://example.test/next"}],
        ["AC_web_run", {"action": "WR_left_click", "params": {"element_name": "#mine-2"}}],
    ]


def test_an_event_with_no_sending_tab_is_refused(recorder):
    recorder.request(_START)
    assert recorder.request(_click("#popup"), None) == {"ok": False, "reason": "not the recording tab"}


def test_start_without_a_tab_does_not_record(recorder):
    reply = recorder.request({"command": "start", "startUrl": "https://example.test/"})
    assert reply == {"ok": False, "reason": "no tab to record"}
    assert recorder.request(_click("#x"), _TAB) == {"ok": False, "reason": "not recording"}


def test_closing_the_recording_tab_ends_the_recording(recorder):
    recorder.request(_START)
    recorder.run(f"__ext.listeners.removed({_OTHER_TAB}, {{}})")
    recorder.drain()
    assert recorder.stored_state()["recording"] is True
    recorder.run(f"__ext.listeners.removed({_TAB}, {{}})")
    recorder.drain()
    assert recorder.stored_state()["recording"] is False
    assert recorder.request(_click("#after-close"), _TAB) == {"ok": False, "reason": "not recording"}
