"""Run the web viewer's session code in Qt's JavaScript engine against fake WebRTC objects.

There is no browser in CI, so ``viewer-session.js`` and the page functions
that use it are evaluated in ``QJSEngine`` with fake data channels, peer
connections and media tracks, and the tests read back what was sent and which
tracks were stopped.
"""
import json
import re
from pathlib import Path

import pytest

import je_auto_control

_WEB = Path(je_auto_control.__file__).parent / "utils" / "remote_desktop" / "web_viewer"
_PAGE = (_WEB / "index.html").read_text(encoding="utf-8")


def _page_part(name: str) -> str:
    """The source of the top-level ``function name`` or ``const name`` in ``index.html``."""
    match = re.search(rf"^(?:async )?(?:function {name}\(|const {name} = ).*?^}};?$",
                      _PAGE, re.MULTILINE | re.DOTALL)
    assert match, f"{name} not found in index.html"
    # A top-level const lives only in the script that declared it; var is global.
    return re.sub(r"^const ", "var ", match.group(0))


@pytest.fixture(scope="module")
def qt_core():
    qt_core = pytest.importorskip("PySide6.QtCore")
    pytest.importorskip("PySide6.QtQml")
    app = qt_core.QCoreApplication.instance() or qt_core.QCoreApplication([])
    return app


class _Js:
    """One QJSEngine with ``viewer-session.js`` loaded."""

    def __init__(self, app) -> None:
        from PySide6.QtQml import QJSEngine
        self._app = app
        self.engine = QJSEngine()
        self.run((_WEB / "viewer-session.js").read_text(encoding="utf-8"))

    def run(self, source: str):
        result = self.engine.evaluate(source)
        assert not result.isError(), result.toString()
        self._app.processEvents()  # promise reactions run from the event loop
        return result

    def value(self, expression: str):
        return json.loads(self.run(f"JSON.stringify({expression})").toString())


@pytest.fixture
def js(qt_core):
    return _Js(qt_core)


_CHANNEL_FAKES = """
var log = [];
var controlChannel = null, micChannel = null, filesChannel = null;
var els = { token: { value: "tok" } };
var viewerId = "viewer-1";
function handleControlMessage() {}
function wireIncomingFiles() {}
function fakeChannel(label) {
  return { label: label, readyState: "connecting", onopen: null, onmessage: null,
           send: function (text) { log.push(label + "/" + JSON.parse(text).type); } };
}
function deliver(channel) {
  routeDataChannel(channel, CHANNEL_ROUTES);
  channel.readyState = "open";
  if (channel.onopen) channel.onopen();
}
"""


def _load_channel_page(js: _Js) -> None:
    js.run(_CHANNEL_FAKES + "\n".join(
        _page_part(name) for name in ("CHANNEL_ROUTES", "adoptControlChannel", "sendAuth", "send")))


@pytest.mark.parametrize("order", [["ctrl", "mic", "files", "usb"], ["usb", "files", "mic", "ctrl"]])
def test_only_the_ctrl_channel_carries_auth_and_input(js, order):
    _load_channel_page(js)
    js.run("".join(f'deliver(fakeChannel("{label}"));' for label in order))
    js.run('send({ type: "input", payload: { action: "ping" } });')
    assert js.value("log") == ["ctrl/auth", "ctrl/input"]
    assert js.value("[controlChannel.label, micChannel.label, filesChannel.label]") == ["ctrl", "mic", "files"]


def test_usb_arriving_after_auth_does_not_take_over_the_control_channel(js):
    _load_channel_page(js)
    js.run('deliver(fakeChannel("ctrl")); var usb = fakeChannel("usb"); usb.readyState = "open"; deliver(usb);')
    js.run('send({ type: "input", payload: { action: "ping" } });')
    assert js.value("log") == ["ctrl/auth", "ctrl/input"]
    assert js.value("usb.onopen === null && usb.onmessage === null") is True


def test_route_reports_an_unsupported_label_as_unhandled(js):
    _load_channel_page(js)
    assert js.value('routeDataChannel(fakeChannel("usb"), CHANNEL_ROUTES)') is False
    assert js.value('routeDataChannel(fakeChannel("ctrl"), CHANNEL_ROUTES)') is True


def test_page_loads_the_session_script_and_the_worker_caches_it():
    assert '<script src="viewer-session.js"></script>' in _PAGE
    assert '"./viewer-session.js"' in (_WEB / "sw.js").read_text(encoding="utf-8")


def test_signaling_server_serves_the_session_script():
    testclient = pytest.importorskip("fastapi.testclient")
    from je_auto_control.utils.remote_desktop.signaling_server import create_app
    client = testclient.TestClient(create_app(shared_secret="s3cret", serve_web_viewer=True))
    response = client.get("/viewer/viewer-session.js")
    assert response.status_code == 200
    assert "function routeDataChannel" in response.text
