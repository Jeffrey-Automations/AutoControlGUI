"""Own authenticated macOS stream channels and protected listeners, with the Linux lease owner.

macOS Unix sockets have neither sequenced packets nor per-message credentials, so
a channel carries frames as a 4-byte big-endian length followed by the encoded
frame, and the connector is authenticated once, from the socket's audit token,
when the channel is captured. Before a frame is delivered and around every send,
the retained peer must still be alive with the same identity. A frame that does
not arrive whole within its operation deadline revokes the channel, as a Linux
timeout does, so a partial frame can never be resumed as the start of another.
This establishes ordinary kernel process identity, never physical input authority
or protection against a same-account process the socket descriptor is handed to.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import errno
from pathlib import Path
import socket
import struct
import sys
import threading
from typing import Any

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.presence_channel_linux import (
    _Owner, _budget, _close_socket, _deadline, accept_channel,
)
from je_auto_control.utils.agent_runtime.presence_endpoint_darwin import (
    DarwinEndpoint, DarwinEndpointCheck, DarwinEndpointFiles,
)
from je_auto_control.utils.agent_runtime.presence_frames import decode_frame, encode_frame
from je_auto_control.utils.agent_runtime.presence_peer_darwin import DarwinPeerProcess, retain_connected_peer

_FRAME_LIMIT = 4096
_HEADER = struct.Struct('>I')


def _new_socket() -> socket.socket:
    if sys.platform != 'darwin':
        raise AgentTaskError('macOS helper channels are unavailable on this platform')
    connection = socket.socket(getattr(socket, 'AF_UNIX'), socket.SOCK_STREAM)
    try:
        _configure(connection)
        return connection
    except BaseException:
        _close_socket(connection)
        raise


def _configure(connection: socket.socket) -> None:
    if connection.family != getattr(socket, 'AF_UNIX') or connection.type != socket.SOCK_STREAM:
        raise AgentTaskError('macOS channel requires a Unix stream socket')
    connection.setblocking(False)
    if connection.get_inheritable():
        raise AgentTaskError('macOS channel descriptor must be noninheritable')


@dataclass
class _ChannelResources:
    connection: socket.socket
    peer: DarwinPeerProcess
    pending: bytearray = field(default_factory=bytearray)

    def close(self) -> None:
        """Attempt socket and retained peer retirement even if one fails."""
        try:
            _close_socket(self.connection)
        finally:
            self.peer.close()


@dataclass
class _ListenerResources:
    connection: socket.socket
    files: DarwinEndpointFiles

    def close(self) -> None:
        """Attempt listener and owned pathname retirement even if one fails."""
        try:
            _close_socket(self.connection)
        finally:
            self.files.close()


def _capture(connection: socket.socket) -> DarwinChannel:
    peer = None
    try:
        connection.set_inheritable(False)  # an accepted socket; already so for one this process connected
        _configure(connection)
        peer = retain_connected_peer(connection)
        channel = object.__new__(DarwinChannel)
        # pylint: disable-next=protected-access  # reason: only this exact-socket factory installs ownership.
        channel._owner = _Owner(_ChannelResources(connection, peer))  # type: ignore[arg-type]
        return channel
    except BaseException:
        try:
            _close_socket(connection)
        finally:
            if peer is not None:
                peer.close()
        raise


def _connect(connection: socket.socket, address: str, deadline: float, cancel: threading.Event | None) -> None:
    pending = {errno.EINPROGRESS, errno.EALREADY, errno.EINTR}
    while True:
        interval = _budget(deadline, cancel)
        result = connection.connect_ex(address)
        if result in {0, errno.EISCONN}:
            return
        if result not in pending | {errno.EAGAIN}:
            raise AgentTaskError('macOS endpoint connection was refused')
        (cancel or threading.Event()).wait(interval)


def _take_frame(pending: bytearray) -> bytes | None:
    """Remove one whole frame from the buffer, or None while it is still incomplete."""
    if len(pending) < _HEADER.size:
        return None
    length, = _HEADER.unpack_from(pending)
    if not 1 <= length <= _FRAME_LIMIT:
        raise AgentTaskError('macOS frame is empty or oversized')
    if len(pending) < _HEADER.size + length:
        return None
    raw = bytes(pending[_HEADER.size:_HEADER.size + length])
    del pending[:_HEADER.size + length]
    return raw


def _missing(pending: bytearray) -> int:
    """How many bytes the frame at the front of an incomplete buffer still needs.

    Never more than that is read: a following frame stays in the socket, where the caller's
    wait for readability can see it.
    """
    if len(pending) < _HEADER.size:
        return _HEADER.size - len(pending)
    length, = _HEADER.unpack_from(pending)
    return int(_HEADER.size + length - len(pending))


def frame_bytes(frame: dict[str, Any]) -> bytes:
    """One length-prefixed encoded frame."""
    raw = encode_frame(frame)
    if not 1 <= len(raw) <= _FRAME_LIMIT:
        raise AgentTaskError('macOS frame is empty or oversized')
    return _HEADER.pack(len(raw)) + raw


class DarwinChannel:
    """One exact socket and original peer, with length-prefixed frame delivery.

    Close revokes delivery immediately. Retirement follows the shared lease owner:
    a stalled operation keeps the resources until it ends, and a bounded close
    reports retirement unconfirmed meanwhile.
    """

    _owner: _Owner[Any]

    def __init__(self) -> None:
        raise AgentTaskError('macOS channels must be created by connect or listener accept')

    @classmethod
    def connect(cls, endpoint: DarwinEndpoint, *, timeout: float,
                cancel: threading.Event | None = None) -> DarwinChannel:
        """Connect to trusted immutable launch metadata and pin the actual listener."""
        deadline = _deadline(timeout)
        _budget(deadline, cancel)
        connection, channel, check = None, None, None
        try:
            connection = _new_socket()
            check = DarwinEndpointCheck(endpoint)
            _connect(connection, check.address, deadline, cancel)
            owned, connection = connection, None
            channel = _capture(owned)
            check.verify()
            with channel._owner.operation(deadline, cancel) as resources:
                if resources.peer.identity != endpoint.listener_process or not resources.peer.alive():
                    raise AgentTaskError('macOS endpoint listener differs from the trusted launch identity')
            check.close()
            check = None
            result, channel = channel, None
            return result
        except (OSError, UnicodeError, NotImplementedError):
            raise AgentTaskError('macOS endpoint cannot be connected securely') from None
        finally:
            try:
                if check is not None:
                    check.close()
            finally:
                try:
                    if connection is not None:
                        _close_socket(connection)
                finally:
                    if channel is not None:
                        channel.close()

    def fileno(self) -> int:
        """Return the connected descriptor for peer evidence and readiness waits; it never delivers data."""
        with self._owner.operation(_deadline(1), None) as resources:
            return resources.connection.fileno()

    def receive(self, *, timeout: float, cancel: threading.Event | None = None) -> dict[str, Any]:
        """Receive one whole frame from the still-live original connector."""
        deadline = _deadline(timeout)
        with self._owner.operation(deadline, cancel) as resources:
            while True:
                raw = _take_frame(resources.pending)
                if raw is not None:
                    if not resources.peer.alive():
                        raise AgentTaskError('macOS channel original peer has retired')
                    return decode_frame(raw)
                self._owner.ready(resources.connection, deadline, cancel)
                try:
                    chunk = resources.connection.recv(_missing(resources.pending))
                except (BlockingIOError, InterruptedError):
                    continue
                if not chunk:
                    raise AgentTaskError('macOS channel peer closed the connection')
                resources.pending.extend(chunk)

    def send(self, frame: dict[str, Any], *, timeout: float, cancel: threading.Event | None = None) -> None:
        """Send exactly one frame while retaining the original live peer."""
        deadline = _deadline(timeout)
        with self._owner.operation(deadline, cancel) as resources:
            raw = memoryview(frame_bytes(frame))
            if not resources.peer.alive():
                raise AgentTaskError('macOS channel original peer has retired')
            while raw:
                self._owner.ready(resources.connection, deadline, cancel, write=True)
                try:
                    sent = resources.connection.send(raw)
                except (BlockingIOError, InterruptedError):
                    continue
                raw = raw[sent:]
            if not resources.peer.alive():
                raise AgentTaskError('macOS channel original peer retired during send')

    def close(self, *, timeout: float = 0.25) -> None:
        """Revoke the channel and bound userspace waiting for resource retirement."""
        self._owner.close(timeout)

    def __enter__(self) -> DarwinChannel:
        return self

    def __exit__(self, *_arguments: object) -> None:
        self.close()


class DarwinListener:
    """Own a fresh protected endpoint; returned channels have independent lifetimes."""

    _owner: _Owner[Any]
    _endpoint: DarwinEndpoint

    def __init__(self) -> None:
        raise AgentTaskError('macOS listeners must be created by create')

    @classmethod
    def create(cls, runtime_directory: str | Path) -> DarwinListener:
        """Create a new 0700 directory and 0600 stream listener."""
        connection, files = None, None
        try:
            connection = _new_socket()
            files = DarwinEndpointFiles(runtime_directory)
            endpoint = files.bind(connection)
            connection.listen(8)
            listener = object.__new__(cls)
            listener._owner = _Owner(_ListenerResources(connection, files))  # type: ignore[arg-type]
            listener._endpoint = endpoint
            connection, files = None, None
            return listener
        except (OSError, UnicodeError, NotImplementedError):
            raise AgentTaskError('macOS listener cannot be created securely') from None
        finally:
            try:
                if connection is not None:
                    _close_socket(connection)
            finally:
                if files is not None:
                    files.close()

    @property
    def endpoint(self) -> DarwinEndpoint:
        """Return immutable metadata for a future trusted host-owned helper launch."""
        return self._endpoint

    def fileno(self) -> int:
        """Return the listening descriptor for readiness waits; accepting still goes through accept."""
        with self._owner.operation(_deadline(1), None) as resources:
            return resources.connection.fileno()

    def accept(self, *, timeout: float, cancel: threading.Event | None = None) -> DarwinChannel:
        """Accept one channel and bind its retained peer to that exact socket; see ``accept_channel``."""
        return accept_channel(self._owner, _deadline(timeout), cancel, _capture)

    def close(self, *, timeout: float = 0.25) -> None:
        """Revoke pending accepts and retire only listener resources and owned paths."""
        self._owner.close(timeout)

    def __enter__(self) -> DarwinListener:
        return self

    def __exit__(self, *_arguments: object) -> None:
        self.close()
