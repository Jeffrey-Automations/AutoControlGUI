"""``resources/subscribe`` over HTTP delivers ``notifications/resources/updated``.

Over HTTP the handshake-era subscription answered ``{}`` and nothing ever
arrived: the provider's update ran on its own thread, where no notifier is
bound, and the subscription was server-wide rather than the session's. It is
now held per session and delivered down that session's standing ``GET``
stream. A request with no session has no stream to deliver on and is refused
with a JSON-RPC error instead of a ``{}`` that promises updates. Real sockets
on loopback; the resource is a fake whose updates the test fires by hand.
"""
import http.client
import json
import threading

import pytest

from je_auto_control.utils.mcp_server.http_sessions import SESSION_HEADER
from je_auto_control.utils.mcp_server.http_transport import DEFAULT_PATH, HttpMCPServer
from je_auto_control.utils.mcp_server.prompts import StaticPromptProvider
from je_auto_control.utils.mcp_server.resources import MCPResource, ResourceProvider
from je_auto_control.utils.mcp_server.server import MCPServer

_ONE, _TWO = "fake://one", "fake://two"


class _FiringProvider(ResourceProvider):
    """Subscribable resources whose updates the test fires itself."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next = 0
        self.callbacks = {}   # handle -> (uri, on_update)

    def list(self):
        return [MCPResource(uri=_ONE, name="one"), MCPResource(uri=_TWO, name="two")]

    def read(self, uri):
        return {"uri": uri, "mimeType": "text/plain", "text": "x"} if uri in (_ONE, _TWO) else None

    def subscribe(self, uri, on_update):
        if uri not in (_ONE, _TWO):
            return None
        with self._lock:
            self._next += 1
            self.callbacks[self._next] = (uri, on_update)
            return self._next

    def unsubscribe(self, uri, handle):
        with self._lock:
            self.callbacks.pop(handle, None)

    def fire(self, uri):
        with self._lock:
            targets = [callback for watched, callback in self.callbacks.values() if watched == uri]
        for callback in targets:
            callback()


@pytest.fixture
def live():
    provider = _FiringProvider()
    server = HttpMCPServer(mcp=MCPServer(tools=[], resource_provider=provider,
                                         prompt_provider=StaticPromptProvider([])),
                           host="127.0.0.1", port=0)
    server.start()
    try:
        yield server, provider
    finally:
        server.stop(timeout=2.0)


def _connect(server, timeout=20.0):
    host, port = server.address
    return http.client.HTTPConnection(host, port, timeout=timeout)


def _post(server, payload, session_id=None):
    conn = _connect(server)
    try:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if session_id is not None:
            headers[SESSION_HEADER] = session_id
        conn.request("POST", DEFAULT_PATH, body=json.dumps(payload), headers=headers)
        response = conn.getresponse()
        return response, response.read().decode("utf-8")
    finally:
        conn.close()


def _initialize(server):
    response, _body = _post(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "probe", "version": "1"}}})
    assert response.status == 200
    return response.getheader(SESSION_HEADER)


def _subscribe(server, uri, session_id=None, method="resources/subscribe"):
    _response, body = _post(server, {"jsonrpc": "2.0", "id": 7, "method": method,
                                     "params": {"uri": uri}}, session_id)
    return json.loads(body)


def _open_stream(server, session_id):
    # Shorter than the transport's 15 s heartbeat: silence ends the read in a timeout.
    conn = _connect(server, timeout=5.0)
    conn.request("GET", DEFAULT_PATH, headers={SESSION_HEADER: session_id,
                                               "Accept": "text/event-stream"})
    stream = conn.getresponse()
    assert stream.status == 200
    return conn, stream


def _next_event(stream):
    """The next SSE ``data:`` payload; the socket timeout bounds the wait."""
    while True:
        raw = stream.readline()
        if not raw:
            return None
        line = raw.decode("utf-8").rstrip("\r\n")
        if line.startswith("data: "):
            return json.loads(line[len("data: "):])


def test_a_subscribed_session_is_sent_the_update_on_its_stream(live):
    server, provider = live
    session_id = _initialize(server)
    conn, stream = _open_stream(server, session_id)
    try:
        assert _subscribe(server, _ONE, session_id)["result"] == {}
        provider.fire(_ONE)
        event = _next_event(stream)
    finally:
        conn.close()
    assert event == {"jsonrpc": "2.0", "method": "notifications/resources/updated",
                     "params": {"uri": _ONE}}


def test_each_session_is_sent_only_what_it_subscribed_to(live):
    server, provider = live
    first, second = _initialize(server), _initialize(server)
    first_conn, first_stream = _open_stream(server, first)
    second_conn, second_stream = _open_stream(server, second)
    try:
        assert "result" in _subscribe(server, _ONE, first)
        assert "result" in _subscribe(server, _TWO, second)
        provider.fire(_ONE)
        provider.fire(_TWO)
        first_event, second_event = _next_event(first_stream), _next_event(second_stream)
    finally:
        first_conn.close()
        second_conn.close()
    assert first_event["params"] == {"uri": _ONE}
    assert second_event["params"] == {"uri": _TWO}


def test_two_sessions_on_one_resource_each_hold_a_subscription(live):
    server, provider = live
    first, second = _initialize(server), _initialize(server)
    assert "result" in _subscribe(server, _ONE, first)
    assert "result" in _subscribe(server, _ONE, second)
    assert len(provider.callbacks) == 2


def test_unsubscribe_and_ending_the_session_release_the_provider_handle(live):
    server, provider = live
    session_id = _initialize(server)
    assert "result" in _subscribe(server, _ONE, session_id)
    assert "result" in _subscribe(server, _ONE, session_id, method="resources/unsubscribe")
    assert provider.callbacks == {}
    assert "result" in _subscribe(server, _TWO, session_id)
    conn = _connect(server)
    try:
        conn.request("DELETE", DEFAULT_PATH, headers={SESSION_HEADER: session_id})
        assert conn.getresponse().status == 200
    finally:
        conn.close()
    assert provider.callbacks == {}


def test_a_request_without_a_session_is_refused_not_promised_updates(live):
    server, provider = live
    answer = _subscribe(server, _ONE)
    assert answer["error"]["code"] == -32600
    assert "session" in answer["error"]["message"]
    assert provider.callbacks == {}


def test_the_stdio_peer_still_gets_updates_on_its_notifier():
    provider = _FiringProvider()
    server = MCPServer(tools=[], resource_provider=provider)
    sent = []
    server.set_notifier(lambda method, params: sent.append((method, params)))
    answer = json.loads(server.handle_line(json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "resources/subscribe", "params": {"uri": _ONE}})))
    assert answer["result"] == {}
    provider.fire(_ONE)
    assert sent == [("notifications/resources/updated", {"uri": _ONE})]
