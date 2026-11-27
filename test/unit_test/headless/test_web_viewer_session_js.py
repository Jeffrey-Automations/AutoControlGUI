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


_MEDIA_FAKES = """
function fakeTrack(kind) {
  return { kind: kind, readyState: "live", stop: function () { this.readyState = "ended"; } };
}
function fakeStream(kind) {
  var tracks = [fakeTrack(kind)];
  return { getTracks: function () { return tracks.slice(); } };
}
function deferred() {
  var d = {};
  d.promise = new Promise(function (resolve) { d.resolve = resolve; });
  return d;
}
function fakeClosable() {
  return { closed: false, close: function () { this.closed = true; } };
}
function fakeElement() {
  return { textContent: "", disabled: false, style: {}, title: "", srcObject: null,
           classList: { add: function () {}, remove: function () {} } };
}
var els = new Proxy({}, { get: function (made, key) {
  if (!(key in made)) made[key] = fakeElement();
  return made[key];
} });
var document = { getElementById: function (id) { return els[id]; } };
function t(key) { return key; }
function clearInterval() {}
var statsTimer = null, connInfoTimer = null, connectedAt = null;
var pc = fakeClosable(), controlChannel = fakeClosable();
var micChannel = fakeClosable(), filesChannel = fakeClosable();
var micState = { context: fakeClosable(), source: { disconnect: function () {} },
                 worklet: { disconnect: function () {} } };
var localMedia = createLocalMedia();
function grant(stream) { return function () { return Promise.resolve(stream); }; }
"""


def _load_media_page(js: _Js) -> None:
    js.run(_MEDIA_FAKES + "\n".join(
        _page_part(name) for name in ("teardown", "stopMic", "setConnected")))


def test_disconnect_ends_every_local_track_including_a_late_permission(js):
    _load_media_page(js)
    js.run("""
      var opus = fakeStream("audio"), pcm = fakeStream("audio"), screen = fakeStream("video");
      localMedia.acquire("opus", grant(opus));
      localMedia.acquire("pcm", grant(pcm));
      var prompt = deferred(), lateResult = "pending";
      localMedia.acquire("screen", function () { return prompt.promise; })
        .then(function (stream) { lateResult = stream; });
    """)
    assert js.value('[localMedia.get("opus") === opus, localMedia.get("pcm") === pcm]') == [True, True]
    js.run("teardown(); prompt.resolve(screen);")
    states = js.value("[opus, pcm, screen].map(function (s) { return s.getTracks()[0].readyState; })")
    assert states == ["ended", "ended", "ended"]
    assert js.value('["opus", "pcm", "screen"].map(localMedia.get)') == [None, None, None]
    assert js.value("[lateResult, micState, pc, controlChannel]") == [None, None, None, None]


def test_a_second_grant_for_a_held_capture_is_stopped(js):
    js.run(_MEDIA_FAKES + """
      var first = fakeStream("audio"), second = fakeStream("audio"), secondResult = "pending";
      localMedia.acquire("opus", grant(first));
      localMedia.acquire("opus", grant(second)).then(function (s) { secondResult = s; });
    """)
    assert js.value('localMedia.get("opus") === first') is True
    assert js.value("[first.getTracks()[0].readyState, second.getTracks()[0].readyState, secondResult]") == [
        "live", "ended", None]


def test_release_stops_the_named_capture_and_returns_it(js):
    js.run(_MEDIA_FAKES + 'var mic = fakeStream("audio"); localMedia.acquire("opus", grant(mic));')
    assert js.value('localMedia.release("opus") === mic') is True
    assert js.value('[mic.getTracks()[0].readyState, localMedia.get("opus"), localMedia.release("opus")]') == [
        "ended", None, None]


_WEB_EVENTS = """[
  inputMessage("mouse_move", { x: 10, y: 20 }),
  buttonMessage("mouse_press", [10, 20], 2),
  buttonMessage("mouse_release", [10, 20], 0),
  wheelMessage([5, 6], 120),
  wheelMessage([5, 6], -40),
  keyMessage("a"),
  keyMessage("Shift"),
]"""


def test_web_input_events_drive_the_host_dispatcher(js, monkeypatch):
    from je_auto_control.utils.remote_desktop import input_dispatch
    calls = []

    def recorder(name):
        return lambda *args: calls.append((name, args))

    monkeypatch.setattr(input_dispatch, "_import_wrappers", lambda: {
        name: recorder(name) for name in (
            "set_mouse_position", "press_mouse", "release_mouse", "mouse_scroll", "write")})
    messages = [message for message in js.value(_WEB_EVENTS) if message is not None]
    assert len(messages) == 6  # a key with no text of its own sends nothing
    for message in messages:
        assert message["type"] == "input"  # what the host's ctrl handler routes on
        input_dispatch.dispatch_input(message["payload"])
    assert calls == [
        ("set_mouse_position", (10, 20)),
        ("press_mouse", ("mouse_right",)),
        ("release_mouse", ("mouse_left",)),
        ("mouse_scroll", (-3, 5, 6)),
        ("mouse_scroll", (3, 5, 6)),
        ("write", ("a",)),
    ]


def test_page_sends_input_only_through_the_shared_builders():
    handlers = _PAGE[_PAGE.index('els.screen.addEventListener("mousemove"'):_PAGE.index("els.connect.addEventListener")]
    assert "payload" not in handlers
    for builder in ('inputMessage("mouse_move"', 'buttonMessage("mouse_press"', 'buttonMessage("mouse_release"',
                    "wheelMessage(", "keyMessage("):
        assert builder in handlers
