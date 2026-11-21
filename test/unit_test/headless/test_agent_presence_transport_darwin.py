"""macOS presence transport: closed wire, framing and peer evidence everywhere; real sockets on macOS. No Qt."""
from __future__ import annotations

import os
import subprocess  # nosec B404  # reason: a fixed child interpreter connects to a test-owned socket
import sys
import tempfile
import threading
from dataclasses import replace

import pytest

from je_auto_control.utils.agent_runtime import presence_endpoint_wire, presence_peer_darwin as peer_module
from je_auto_control.utils.agent_runtime import presence_platform
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.presence_channel_darwin import _take_frame, frame_bytes
from je_auto_control.utils.agent_runtime.presence_endpoint_darwin import DarwinEndpoint, socket_path
from je_auto_control.utils.agent_runtime.presence_endpoint_linux import FileIdentity
from je_auto_control.utils.agent_runtime.presence_peer_darwin import DarwinPeerIdentity
from je_auto_control.utils.agent_runtime.presence_pipe_darwin import (
    endpoint_from_wire, endpoint_to_wire, runtime_directory,
)


def wire():
    identity = {"device": 1, "inode": 2, "owner": 501, "mode": 0o40700}
    return {"platform": "darwin", "directory": "/private/var/folders/ab/cd/T/pr-0123456789abcdef",
            "socket_name": "channel.sock", "directory_identity": identity,
            "socket_identity": {**identity, "inode": 3, "mode": 0o140600},
            "listener_process": {"pid": 77, "uid": 501, "gid": 20, "birth": 9001}}


# --- wire -------------------------------------------------------------------------------------

def test_the_macos_wire_round_trips_through_its_closed_schema():
    endpoint = endpoint_from_wire(wire())
    assert isinstance(endpoint, DarwinEndpoint)
    assert endpoint.listener_process == DarwinPeerIdentity(77, 501, 20, 9001)
    assert endpoint_to_wire(endpoint) == wire()


def test_the_neutral_wire_dispatches_on_shape_not_on_the_running_platform():
    endpoint = presence_endpoint_wire.endpoint_from_wire(wire())
    assert isinstance(endpoint, DarwinEndpoint)
    assert presence_endpoint_wire.endpoint_to_wire(endpoint) == wire()
    linux = {key: value for key, value in wire().items() if key != "platform"}
    with pytest.raises(AgentTaskError, match="Linux"):
        presence_endpoint_wire.endpoint_from_wire(linux)  # parsed, and refused, by the Linux schema


@pytest.mark.parametrize("change", [
    {"platform": "linux"}, {"socket_name": "other.sock"}, {"directory": "relative/pr-1"},
    {"directory": "/" + "x" * 95}, {"directory": "/tmp/a b"}, {"extra": 1},
    {"listener_process": {"pid": 0, "uid": 501, "gid": 20, "birth": 9001}},
    {"listener_process": {"pid": 77, "uid": 501, "gid": 20, "birth": 0}},
    {"listener_process": {"pid": 77, "uid": 501, "gid": 20}},
    {"socket_identity": {"device": 1, "inode": 2, "owner": 501, "mode": True}},
])
def test_malformed_macos_endpoints_are_refused(change):
    with pytest.raises(AgentTaskError):
        endpoint_from_wire({**wire(), **change})


def test_socket_paths_that_would_not_fit_sun_path_are_refused():
    assert socket_path("/private/tmp/pr-1") == "/private/tmp/pr-1/channel.sock"
    with pytest.raises(AgentTaskError, match="address limit"):
        socket_path("/" + "d" * 95)


def test_runtime_directory_prefers_a_canonical_absolute_tmpdir(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "confstr_names", {}, raising=False)
    assert runtime_directory({"TMPDIR": str(tmp_path)}) == os.path.realpath(tmp_path)
    for environ in ({}, {"TMPDIR": "relative"}):
        with pytest.raises(AgentTaskError, match="per-user temporary"):
            runtime_directory(environ)


@pytest.mark.parametrize("platform, pipe, security", [
    ("darwin", "DarwinPresencePipe", "DarwinPresenceSecurity"),
    ("linux", "LinuxPresencePipe", "LinuxPresenceSecurity"),
    ("win32", "WindowsPresencePipe", "WindowsPresenceSecurity"),
])
def test_each_platform_gets_its_own_transport(monkeypatch, platform, pipe, security):
    monkeypatch.setattr(presence_platform.sys, "platform", platform)
    assert type(presence_platform.default_presence_pipe()).__name__ == pipe
    assert type(presence_platform.default_presence_security()).__name__ == security


# --- framing ----------------------------------------------------------------------------------

def test_frames_are_length_prefixed_and_taken_only_when_whole():
    raw = frame_bytes({"protocol": 1, "challenge": "ab"})
    pending = bytearray(raw[:3])
    assert _take_frame(pending) is None
    pending.extend(raw[3:-1])
    assert _take_frame(pending) is None
    pending.extend(raw[-1:] + raw)
    first = _take_frame(pending)
    assert first == raw[4:] and bytes(pending) == raw
    assert _take_frame(pending) == raw[4:] and not pending


@pytest.mark.parametrize("header", [b"\0\0\0\0", (4097).to_bytes(4, "big")])
def test_empty_or_oversized_frame_lengths_are_refused(header):
    with pytest.raises(AgentTaskError, match="empty or oversized"):
        _take_frame(bytearray(header + b"x"))


# --- peer evidence, with the native reads replaced ---------------------------------------------

class FakeProc:
    def __init__(self):
        self.unique = {77: (9001, 5)}
        self.account = {77: (501, 20)}

    def install(self, monkeypatch):
        monkeypatch.setattr(peer_module, "_unique", lambda pid: self.unique.get(pid))

        def account(pid, uid, gid):
            if pid not in self.account:
                return False
            if self.account[pid] != (uid, gid):
                raise AgentTaskError("macOS connected-peer credentials differ from the current account")
            return True
        monkeypatch.setattr(peer_module, "_account", account)


class FakeQueue:
    def __init__(self):
        self.exited, self.closed = False, False

    def close(self):
        self.closed = True


@pytest.fixture
def native(monkeypatch):
    proc, queue = FakeProc(), FakeQueue()
    proc.install(monkeypatch)
    monkeypatch.setattr(peer_module.sys, "platform", "darwin")
    monkeypatch.setattr(peer_module, "_token", lambda connection: (77, 5, 501, 20))
    monkeypatch.setattr(peer_module, "_current_account", lambda: (501, 20))
    monkeypatch.setattr(peer_module, "_watch", lambda pid: queue)
    monkeypatch.setattr(peer_module, "_exited", lambda value: value.exited)
    return proc, queue


def test_a_connector_is_retained_by_its_boot_unique_identity(native):
    peer = peer_module.retain_connected_peer(object())
    assert peer.identity == DarwinPeerIdentity(77, 501, 20, 9001)
    assert peer.alive()
    peer.close()
    assert native[1].closed and not peer.alive()


def test_a_pid_reused_between_connect_and_the_watch_is_refused(native):
    proc, queue = native
    proc.unique[77] = (9002, 6)  # a different process now holds pid 77
    with pytest.raises(AgentTaskError, match="retired or was replaced"):
        peer_module.retain_connected_peer(object())
    assert queue.closed


@pytest.mark.parametrize("fault", ["exited", "gone", "account"])
def test_a_connector_that_exited_or_is_another_account_is_refused(native, fault, monkeypatch):
    proc, queue = native
    if fault == "exited":
        queue.exited = True
    elif fault == "gone":
        del proc.unique[77]
    else:
        monkeypatch.setattr(peer_module, "_token", lambda connection: (77, 5, 502, 20))
    with pytest.raises(AgentTaskError):
        peer_module.retain_connected_peer(object())
    # Another account is refused from the token alone, before any watch exists; otherwise the watch is closed.
    assert queue.closed is (fault != "account")


def test_liveness_follows_the_exit_watch_and_refuses_a_changed_identity(native):
    proc, queue = native
    peer = peer_module.retain_connected_peer(object())
    proc.unique[77] = (9100, 5)
    with pytest.raises(AgentTaskError, match="identity has changed"):
        peer.alive()
    proc.unique[77] = (9001, 5)
    queue.exited = True
    assert not peer.alive()
    queue.exited = False
    assert not peer.alive()  # an observed exit is sticky


def test_peer_evidence_is_refused_off_macos(monkeypatch):
    monkeypatch.setattr(peer_module.sys, "platform", "linux")
    with pytest.raises(AgentTaskError, match="unavailable on this platform"):
        peer_module.retain_connected_peer(object())


# --- real sockets (macOS only) -----------------------------------------------------------------

darwin = pytest.mark.skipif(sys.platform != "darwin", reason="real macOS Unix sockets and libproc")
GENERATION = "0123456789abcdef" * 2  # the handshake accepts only 32 lowercase hex characters


@pytest.fixture
def runtime():
    with tempfile.TemporaryDirectory(dir=runtime_directory()) as directory:
        os.chmod(directory, 0o700)
        yield os.path.realpath(directory)


@darwin
def test_self_identity_is_boot_unique_and_stable():
    first, second = peer_module.self_identity(), peer_module.self_identity()
    assert first == second and first.pid == os.getpid() and first.birth > 0


@darwin
def test_a_real_listener_and_channel_authenticate_and_exchange_frames(runtime):
    from je_auto_control.utils.agent_runtime.presence_channel_darwin import DarwinChannel, DarwinListener
    listener = DarwinListener.create(runtime)
    try:
        endpoint = listener.endpoint
        assert endpoint.listener_process == peer_module.self_identity()
        accepted = []
        worker = threading.Thread(target=lambda: accepted.append(listener.accept(timeout=1)))
        worker.start()
        client = DarwinChannel.connect(endpoint, timeout=1)
        worker.join(2)
        server = accepted[0]
        client.send({"protocol": 1, "challenge": "c1"}, timeout=1)
        assert server.receive(timeout=1) == {"protocol": 1, "challenge": "c1"}
        server.send({"protocol": 1, "challenge": "c2"}, timeout=1)
        assert client.receive(timeout=1) == {"protocol": 1, "challenge": "c2"}
        client.close()
        server.close()
    finally:
        listener.close()
    assert not os.path.exists(endpoint.directory)


@darwin
def test_the_presence_handshake_runs_over_the_macos_pipe(runtime):
    from je_auto_control.utils.agent_runtime.presence_handshake import client_handshake, server_handshake
    from je_auto_control.utils.agent_runtime.presence_pipe_darwin import (
        DarwinPresencePipe, DarwinPresenceSecurity,
    )
    pipe, security = DarwinPresencePipe(runtime=runtime), DarwinPresenceSecurity()
    listener = pipe.listen()
    try:
        client_pipe = DarwinPresencePipe()
        client_pipe.use(listener.endpoint_wire)
        result = {}

        def serve():
            connection = listener.accept()
            result["server"] = server_handshake(connection, security, GENERATION)
            result["server_pipe"] = connection
        worker = threading.Thread(target=serve)
        worker.start()
        connection = client_pipe.connect()
        generation, peer = client_handshake(connection, security)
        worker.join(3)
        assert generation == GENERATION and peer.alive() and result["server"].alive()
        for item in (peer, result["server"]):
            item.close()
        connection.close()
        result["server_pipe"].close()
    finally:
        listener.close()


@darwin
def test_a_connector_that_exits_is_no_longer_alive(runtime):
    from je_auto_control.utils.agent_runtime.presence_channel_darwin import DarwinListener
    listener = DarwinListener.create(runtime)
    try:
        path = socket_path(listener.endpoint.directory)
        child = subprocess.Popen(  # nosec B603  # reason: fixed interpreter and literal program
            [sys.executable, "-c", "import socket,sys,time; s=socket.socket(socket.AF_UNIX);"
             "s.connect(sys.argv[1]); sys.stdin.readline()", path], stdin=subprocess.PIPE)
        channel = listener.accept(timeout=1)
        try:
            peer = channel._owner._state.resources.peer
            assert peer.identity.pid == child.pid and peer.alive()
            child.stdin.close()
            child.wait(5)
            assert not peer.alive()
        finally:
            channel.close()
    finally:
        listener.close()


@darwin
def test_an_endpoint_naming_another_listener_identity_is_refused(runtime):
    from je_auto_control.utils.agent_runtime.presence_channel_darwin import DarwinChannel, DarwinListener
    listener = DarwinListener.create(runtime)
    try:
        forged = replace(listener.endpoint,
                         listener_process=replace(listener.endpoint.listener_process, birth=1))
        threading.Thread(target=lambda: listener.accept(timeout=1).close(), daemon=True).start()
        with pytest.raises(AgentTaskError, match="differs from the trusted launch identity"):
            DarwinChannel.connect(forged, timeout=1)
        replaced = replace(listener.endpoint, socket_identity=FileIdentity(0, 0, 0, 0))
        with pytest.raises(AgentTaskError):
            DarwinChannel.connect(replaced, timeout=1)
    finally:
        listener.close()
