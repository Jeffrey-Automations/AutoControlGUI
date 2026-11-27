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
