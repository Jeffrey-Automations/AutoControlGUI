"""The TCP socket server authenticates every connection (owner decision, 2026-11).

It used to run any command for any local process -- admin-only ones and
``quit_server`` included -- and ignored RBAC. Loopback only, ephemeral ports,
and probe commands registered for the test: nothing touches the desktop.
"""
import json
import logging
import os
import socket
import stat
import sys
import time

import pytest

from je_auto_control.utils.action_signing._private_file import exposure
from je_auto_control.utils.executor.action_executor import executor
from je_auto_control.utils.rbac import USERS_ENV
from je_auto_control.utils.rbac.users import UserStore
from je_auto_control.utils.socket_server import auto_control_socket_server as module
from je_auto_control.utils.socket_server.socket_auth import TOKEN_ENV, SocketAuthError, default_token_path
from je_auto_control.utils.socket_server.socket_client import read_socket_token, send_socket_command

_PROBE = "AC_socket_auth_probe"
_ADMIN_ONLY = "AC_audit_log_clear"  # needs manage_hosts
_END = b"Return_Data_Over_JE"
_NL = bytes([10])
_WAIT = 10.0
_ENV = (USERS_ENV, TOKEN_ENV, "JE_AUTOCONTROL_REQUIRE_SIGNED_ACTIONS",
        "JE_AUTOCONTROL_ACTION_SIGNING_PUBLIC_KEY")


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def probe(monkeypatch):
    calls = []
    monkeypatch.setitem(executor.event_dict, _PROBE, lambda value=None: calls.append(value) or value)
    monkeypatch.setitem(executor.event_dict, _ADMIN_ONLY, lambda: calls.append("admin-only") or "cleared")
    return calls


@pytest.fixture
def start(tmp_path):
    servers = []

    def _start(**kwargs):
        kwargs.setdefault("token_path", tmp_path / "socket.token")
        server = module.start_autocontrol_socket_server("127.0.0.1", 0, **kwargs)
        servers.append(server)
        return server

    yield _start
    for server in servers:
        server.shutdown()
        server.server_close()


def _exchange(server, *messages, read_to_eof=False):
    """Send each message, then read up to the end-of-reply marker (or EOF)."""
    with socket.create_connection(server.server_address[:2], timeout=_WAIT) as connection:
        for message in messages:
            connection.sendall(message)
        if read_to_eof:
            connection.shutdown(socket.SHUT_WR)  # nothing more is coming
        reply = b""
        while read_to_eof or _END not in reply:
            chunk = connection.recv(65536)
            if not chunk:
                break
            reply += chunk
    return reply.decode("utf-8")


def _auth(token):
    return f"AUTH {token}".encode("utf-8") + _NL


def _command(actions):
    return json.dumps(actions).encode("utf-8") + _NL


def _is_serving(server):
    return server.socket.fileno() != -1


# --- no token, no command ---------------------------------------------------------------------

def test_a_command_without_auth_is_refused_and_not_run(start, probe):
    server = start()
    reply = _exchange(server, _command([[_PROBE, {"value": "x"}]]))
    assert "authentication required" in reply
    assert reply.endswith(_END.decode() + chr(10))
    assert probe == []


def test_quit_server_without_auth_does_not_stop_the_server(start):
    server = start()
    reply = _exchange(server, b"quit_server" + _NL)
    assert "authentication required" in reply
    time.sleep(0.3)
    assert _is_serving(server)


def test_a_wrong_token_is_refused_and_the_command_not_run(start, probe):
    server = start()
    reply = _exchange(server, _auth("wrong"), _command([[_PROBE, {"value": "x"}]]))
    assert "authentication failed" in reply
    assert "AUTH_OK" not in reply
    assert probe == []


def test_the_connection_closes_after_three_wrong_tokens(start, monkeypatch):
    monkeypatch.setattr(module, "_AUTH_DEADLINE_S", 8.0)
    server = start()
    started = time.monotonic()
    with socket.create_connection(server.server_address[:2], timeout=_WAIT) as connection:
        connection.sendall(_auth("a") + _auth("b") + _auth("c"))
        reply = b""
        while True:  # the server closes; it does not wait for a fourth attempt
            chunk = connection.recv(65536)
            if not chunk:
                break
            reply += chunk
    assert reply.decode().count("authentication failed") == 3
    assert time.monotonic() - started < 4


def test_a_silent_client_is_dropped_at_the_auth_deadline(start, monkeypatch):
    monkeypatch.setattr(module, "_AUTH_DEADLINE_S", 0.5)
    server = start()
    with socket.create_connection(server.server_address[:2], timeout=_WAIT) as connection:
        connection.sendall(b"AU")  # starts, never finishes
        started = time.monotonic()
        assert connection.recv(1024) == b""
    assert time.monotonic() - started < 5


def test_failed_attempts_are_rate_limited_per_client_but_the_token_still_works(start, probe):
    server = start()
    for _ in range(4):
        _exchange(server, _auth("x") + _auth("y"), read_to_eof=True)
    reply = _exchange(server, _auth("z"))
    assert "too many failed attempts" in reply
    reply = _exchange(server, _auth(server.token), _command([[_PROBE, {"value": "ok"}]]))
    assert reply.startswith("AUTH_OK")
    assert probe == ["ok"]


# --- the server token ------------------------------------------------------------------------

def test_the_server_token_authenticates_and_the_command_runs(start, probe):
    server = start()
    reply = _exchange(server, _auth(server.token), _command([[_PROBE, {"value": "ran"}]]))
    assert reply.splitlines()[:2] == ["AUTH_OK", "ran"]
    assert probe == ["ran"]


def test_the_token_is_random_and_written_owner_only(start, tmp_path):
    first, second = start(token_path=tmp_path / "a.token"), start(token_path=tmp_path / "b.token")
    assert first.token != second.token and len(first.token) >= 43  # token_urlsafe(32)
    assert first.token_path.read_text(encoding="utf-8").strip() == first.token
    assert exposure(first.token_path) == []
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(first.token_path).st_mode) == 0o600


def test_the_default_token_path_is_per_port_under_the_home(start, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    server = start(token_path=None)
    port = server.server_address[1]
    expected = tmp_path / ".je_auto_control" / f"socket_server_{port}.token"
    assert default_token_path(port) == expected
    assert server.token_path == expected
    assert read_socket_token(port) == server.token


def test_an_explicit_token_and_the_environment_token_are_used(start, monkeypatch, probe):
    assert start(token="explicit-token").token == "explicit-token"
    monkeypatch.setenv(TOKEN_ENV, "environment-token")
    server = start()
    assert server.token == "environment-token"
    assert send_socket_command([[_PROBE, {"value": 1}]], port=server.server_address[1],
                               token="environment-token") == ["1"]


def test_closing_the_server_removes_its_token_file(start):
    server = start()
    path = server.token_path
    assert path.exists()
    server.shutdown()
    server.server_close()
    assert not path.exists()


# --- the client helper -----------------------------------------------------------------------

def test_the_client_reads_the_token_file_and_quits_the_server(start, probe):
    server = start()
    port, path = server.server_address[1], server.token_path
    assert send_socket_command([[_PROBE, {"value": "c"}]], port=port, token_path=path) == ["c"]
    assert send_socket_command("quit_server", port=port, token_path=path) == []
    deadline = time.monotonic() + _WAIT
    while _is_serving(server) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _is_serving(server)


def test_the_client_raises_on_a_refused_token(start):
    server = start()
    with pytest.raises(SocketAuthError, match="authentication failed"):
        send_socket_command([[_PROBE]], port=server.server_address[1], token="not-it")


# --- the legacy opt-out ----------------------------------------------------------------------

def test_require_auth_false_serves_legacy_clients_and_warns(start, probe, caplog):
    with caplog.at_level(logging.WARNING, logger="AutoControlGUI"):
        server = start(require_auth=False)
    assert "WITHOUT authentication" in caplog.text
    assert server.token_path is None
    port = server.server_address[1]
    assert send_socket_command([[_PROBE, {"value": "old"}]], port=port, require_auth=False) == ["old"]
    assert send_socket_command([[_PROBE, {"value": "new"}]], port=port, token="anything") == ["new"]
    assert probe == ["old", "new"]


def test_a_server_built_without_a_policy_refuses_everything(start, probe):
    server = start()
    server.socket_auth = None
    reply = _exchange(server, _auth("anything"), _command([[_PROBE, {"value": "x"}]]))
    assert "authentication failed" in reply
    assert probe == []


# --- RBAC ------------------------------------------------------------------------------------

@pytest.fixture
def users(tmp_path, monkeypatch):
    path = tmp_path / "users.json"
    store = UserStore(path)
    tokens = {role: store.add_user(user_id=role, display_name=role, role=role)
              for role in ("viewer", "operator", "admin")}
    monkeypatch.setenv(USERS_ENV, str(path))
    return tokens


def test_under_rbac_a_user_token_authenticates_and_the_server_token_does_not(start, users, probe):
    server = start(token="server-token")
    assert server.token is None and server.token_path is None
    port = server.server_address[1]
    with pytest.raises(SocketAuthError):
        send_socket_command([[_PROBE]], port=port, token="server-token")
    assert send_socket_command([[_PROBE, {"value": "op"}]], port=port, token=users["operator"]) == ["op"]
    assert probe == ["op"]


def test_under_rbac_a_viewer_may_not_run_actions(start, users, probe):
    server = start()
    reply = send_socket_command([[_PROBE, {"value": "v"}]], port=server.server_address[1],
                                token=users["viewer"])
    assert "forbidden" in reply[0] and "drive_input" in reply[0]
    assert probe == []


def test_under_rbac_an_operator_may_not_run_an_admin_only_command(start, users, probe):
    server = start()
    port = server.server_address[1]
    reply = send_socket_command([[_PROBE, {"value": "first"}], [_ADMIN_ONLY]], port=port,
                                token=users["operator"])
    assert "forbidden" in reply[0] and _ADMIN_ONLY in reply[0]
    assert probe == [], "the whole command is refused before its first action"
    assert send_socket_command([[_ADMIN_ONLY]], port=port, token=users["admin"]) == ["cleared"]


def test_under_rbac_a_nested_admin_only_command_runs_under_the_callers_role(start, users, probe, tmp_path):
    flow = tmp_path / "flow.json"
    flow.write_text(json.dumps([[_ADMIN_ONLY]]), encoding="utf-8")
    server = start()
    send_socket_command([["AC_execute_files", {"execute_files_list": [str(flow)]}]],
                        port=server.server_address[1], token=users["operator"])
    assert probe == [], "the executor refused it inside the operator's scope"


def test_under_rbac_only_an_admin_may_quit_the_server(start, users):
    server = start()
    port = server.server_address[1]
    reply = send_socket_command("quit_server", port=port, token=users["operator"])
    assert "forbidden" in reply[0] and "manage_hosts" in reply[0]
    time.sleep(0.3)
    assert _is_serving(server)
    assert send_socket_command("quit_server", port=port, token=users["admin"]) == []
    deadline = time.monotonic() + _WAIT
    while _is_serving(server) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _is_serving(server)


# --- the CLI ---------------------------------------------------------------------------------

def test_the_cli_writes_the_token_file_and_passes_the_flags(monkeypatch, tmp_path, capsys, probe):
    from je_auto_control import cli
    seen = {}

    def _serve_once(_shutdown):
        path = tmp_path / "cli.token"
        out = capsys.readouterr().out
        assert f"token file: {path}" in out
        port = int(out.splitlines()[0].rsplit(":", 1)[1])
        seen["reply"] = send_socket_command([[_PROBE, {"value": "cli"}]], port=port, token_path=path)
        _shutdown()

    monkeypatch.setattr(cli, "_run_until_signal", _serve_once)
    assert cli.main(["start-server", "--port", "0", "--token-file", str(tmp_path / "cli.token")]) == 0
    assert seen["reply"] == ["cli"]
    assert not (tmp_path / "cli.token").exists(), "removed when the server closed"
    parsed = cli.build_parser().parse_args(["start-server", "--no-auth", "--token", "t"])
    assert parsed.no_auth is True and parsed.token == "t"
