"""How the MCP server admits, cancels and answers messages, stdio and HTTP.

A notification or a reply POSTed with ``Accept: ..., text/event-stream`` --
which every Streamable HTTP client sends -- was answered 200 with an empty
stream instead of 202, so a client that opens its GET stream on the 202 never
did; a cancel that arrived before a call was admitted was dropped and the tool
ran; ``subscriptions/listen`` did not check the right to read what it names;
and a malformed ``Host`` or ``Origin``, or a listen sent as a notification,
raised in the handler thread.
"""
import http.client
import json
import os
import socket
import ssl
import threading

import pytest

from je_auto_control.utils.mcp_server.http_sessions import SESSION_HEADER
from je_auto_control.utils.mcp_server.http_transport import DEFAULT_PATH, HttpMCPServer
from je_auto_control.utils.mcp_server.resources import FileSystemProvider, MCPResource, ResourceProvider
from je_auto_control.utils.mcp_server.server import MCPServer
from je_auto_control.utils.mcp_server.tools import MCPTool, MCPToolAnnotations
from je_auto_control.utils.mcp_server.tools._base import schema
from je_auto_control.utils.rbac.authorization import AuthorizationContext, authorization_scope

_BOTH = "application/json, text/event-stream"
_META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
         "io.modelcontextprotocol/clientCapabilities": {}}
_INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}


@pytest.fixture
def http_server():
    server = HttpMCPServer(mcp=MCPServer(tools=[]), host="127.0.0.1", port=0)
    server.start()
    yield server
    server.stop(timeout=2.0)


def _post(server, payload, **headers):
    connection = http.client.HTTPConnection(*server.address, timeout=10)
    try:
        connection.request("POST", DEFAULT_PATH, body=json.dumps(payload),
                           headers={"Content-Type": "application/json", **headers})
        response = connection.getresponse()
        return response.status, response.getheader(SESSION_HEADER), response.read()
    finally:
        connection.close()


@pytest.mark.parametrize("payload", [
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": "srv-x", "result": {"roots": []}},
])
def test_a_message_that_needs_no_reply_is_accepted_not_streamed(http_server, payload):
    _status, session, _body = _post(http_server, _INIT, Accept=_BOTH)
    status, _session, body = _post(http_server, payload, Accept=_BOTH, **{SESSION_HEADER: session})
    assert (status, body) == (202, b"")


def test_a_request_still_streams_when_the_client_accepts_it(http_server):
    status, _session, body = _post(http_server, {"jsonrpc": "2.0", "id": 5, "method": "ping"}, Accept=_BOTH)
    assert status == 200
    assert body.startswith(b"data: ")


def test_a_listen_notification_does_not_break_the_handler(http_server):
    status, _session, _body = _post(
        http_server, {"jsonrpc": "2.0", "method": "subscriptions/listen",
                      "params": {"_meta": _META, "notifications": {"toolsListChanged": True}}},
        Accept=_BOTH, **{"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "subscriptions/listen"})
    assert status == 202


def test_a_stateless_request_without_params_is_refused_like_one_with_empty_params(http_server):
    headers = {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/list"}
    empty = _post(http_server, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, **headers)
    absent = _post(http_server, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, **headers)
    assert (empty[0], absent[0]) == (400, 400)


@pytest.mark.parametrize("header", ["Origin: http://[", "Host: ["])
def test_a_malformed_origin_or_host_is_refused(http_server, header):
    host = "" if header.startswith("Host") else f"Host: 127.0.0.1:{http_server.address[1]}" + "\r\n"
    request = f"POST {DEFAULT_PATH} HTTP/1.0\r\n{host}{header}\r\nContent-Length: 0\r\n\r\n"
    with socket.create_connection(http_server.address, timeout=5) as client:
        client.sendall(request.encode("ascii"))
        assert b" 403 " in client.recv(4096)


def test_a_failed_tls_setup_leaves_nothing_listening():
    server = HttpMCPServer(mcp=MCPServer(tools=[]), port=0,
                           ssl_context=ssl.create_default_context(ssl.Purpose.SERVER_AUTH))
    with pytest.raises((ssl.SSLError, ValueError)):
        server.start()
    assert server.sessions is None
    stopper = threading.Thread(target=server.stop, daemon=True)
    stopper.start()
    stopper.join(5)
    assert not stopper.is_alive()


# --- cancelling a call that has not been admitted yet -----------------------


def _confirming_server(monkeypatch, ran):
    monkeypatch.setenv("JE_AUTOCONTROL_MCP_CONFIRM_DESTRUCTIVE", "1")
    tool = MCPTool("ac_boom", "d", schema({}), lambda: ran.append("ran"), MCPToolAnnotations(destructive=True))
    server = MCPServer(tools=[tool], concurrent_tools=True)
    sent, prompted, answered = [], threading.Event(), threading.Event()

    def writer(line):
        sent.append(json.loads(line))
        (prompted if sent[-1].get("method") == "elicitation/create" else answered).set()
    server.set_writer(writer)
    server.handle_line(json.dumps({**_INIT, "params": {**_INIT["params"], "capabilities": {"elicitation": {}}}}))
    return server, sent, prompted, answered


def test_a_call_cancelled_while_it_waits_for_confirmation_does_not_run(monkeypatch):
    ran = []
    server, sent, prompted, answered = _confirming_server(monkeypatch, ran)
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                   "params": {"name": "ac_boom", "arguments": {}}}))
    assert prompted.wait(5)
    server.handle_line(json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled",
                                   "params": {"requestId": 7}}))
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": sent[0]["id"], "result": {"action": "accept"}}))
    assert answered.wait(5)
    assert sent[-1]["error"]["code"] == -32800
    assert ran == []
    assert server._active_calls == {}


def test_a_cancel_sent_right_behind_the_call_is_not_lost(monkeypatch):
    ran, release = [], threading.Event()
    server = MCPServer(tools=[MCPTool("ac_go", "d", schema({}), lambda: ran.append("ran"))], concurrent_tools=True)
    sent, done = [], threading.Event()
    server.set_writer(lambda line: (sent.append(json.loads(line)), done.set()))
    original = server._handle_tools_call

    def late(msg_id, params):
        release.wait(5)
        return original(msg_id, params)
    monkeypatch.setattr(server, "_handle_tools_call", late)
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": "ac_go", "arguments": {}}}))
    server.handle_line(json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled",
                                   "params": {"requestId": 1}}))
    release.set()
    assert done.wait(5)
    assert sent[0]["error"]["code"] == -32800
    assert ran == []
    assert server._active_calls == {}


# --- authorisation of subscriptions, malformed roots, resources -------------


class _DataProvider(ResourceProvider):
    subscribed: list = []

    def list(self):
        return [MCPResource("autocontrol://history", "h")]

    def read(self, uri):
        return None

    def subscribe(self, uri, on_update):
        self.subscribed.append(uri)
        return 1


def test_listen_needs_the_right_to_read_what_it_names():
    provider = _DataProvider()
    provider.subscribed = []
    server = MCPServer(tools=[], resource_provider=provider)
    sent = []
    server.set_writer(sent.append)
    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "subscriptions/listen", "params": {
        "_meta": _META, "notifications": {"resourceSubscriptions": ["autocontrol://history"]}}})
    with authorization_scope(AuthorizationContext("v", "viewer")):
        refused = json.loads(server.handle_line(line))
    assert refused["error"]["code"] == -32003
    assert (provider.subscribed, sent, server._listeners) == ([], [], {})
    with authorization_scope(AuthorizationContext("o", "operator")):
        assert server.handle_line(line) is None
    assert provider.subscribed == ["autocontrol://history"]


def test_a_roots_reply_that_is_not_an_object_is_a_contained_failure():
    server = MCPServer(tools=[])

    def writer(line):
        request = json.loads(line)
        server.handle_line(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": ["not", "an", "object"]}))
    server.set_writer(writer)
    with pytest.raises(RuntimeError, match="roots/list"):
        server.refresh_roots(timeout=2.0)
    server._refresh_roots_safely()


def test_files_under_a_root_that_ends_in_a_separator_can_be_read(tmp_path):
    (tmp_path / "a.json").write_text("[]", encoding="utf-8")
    provider = FileSystemProvider(root=str(tmp_path))
    provider.root = str(tmp_path) + os.sep   # what "/" and a drive root look like
    content = provider.read("autocontrol://files/a.json")
    assert content is not None and content["text"] == "[]"
