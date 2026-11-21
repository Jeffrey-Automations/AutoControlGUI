"""Own protected macOS socket paths, reusing the Linux identity checks where POSIX allows.

macOS has no ``/proc/self/fd``, so a socket cannot be bound or connected through a
retained directory descriptor. The path is the canonical per-user temporary
directory joined with a fresh private directory; every ancestor is opened without
following links and checked before use, and the directory and socket identities are
checked again after ``bind``/``connect``, so a replacement between the two is
refused. As on Linux, same-account pathname mutation must be trusted.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import secrets
import socket
from pathlib import Path

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.presence_endpoint_linux import (
    FileIdentity, _EndpointCheck, _EndpointFiles, _UnverifiedPath, _check_directory, _check_socket,
    _close_directory, _directory_flags, _identity, _open_directory,
)
from je_auto_control.utils.agent_runtime.presence_peer_darwin import DarwinPeerIdentity, self_identity

SOCKET_NAME = 'channel.sock'
# sockaddr_un.sun_path is 104 bytes on macOS, including the terminating NUL.
_PATH_LIMIT = 103


@dataclass(frozen=True)
class DarwinEndpoint:
    """Immutable launch metadata, useful only when received through a trusted launch path."""

    directory: str
    directory_identity: FileIdentity
    socket_name: str
    socket_identity: FileIdentity
    listener_process: DarwinPeerIdentity


def socket_path(directory: str, name: str = SOCKET_NAME) -> str:
    """The absolute socket path, refused when it would not fit ``sun_path``."""
    path = f'{directory}/{name}'
    if len(path.encode('utf-8')) > _PATH_LIMIT:
        raise AgentTaskError('macOS presence socket path exceeds the Unix socket address limit')
    return path


class DarwinEndpointFiles(_EndpointFiles):
    """A fresh 0700 directory and 0600 socket under the canonical runtime directory."""

    def __init__(self, runtime: str | Path) -> None:
        if not isinstance(runtime, (str, Path)):
            raise AgentTaskError('macOS runtime directory path is invalid')
        canonical = os.path.realpath(os.fspath(runtime))
        super().__init__(canonical)
        self.name = 'pr-' + secrets.token_hex(8)
        self.directory = f'{canonical}/{self.name}'
        socket_path(self.directory)

    def bind(self, connection: socket.socket) -> DarwinEndpoint:  # type: ignore[override]
        """Record each created object before advancing to the next creation step."""
        os.mkdir(self.name, 0o700, dir_fd=self.parent_fd)
        self.directory_identity = _UnverifiedPath()
        self.directory_identity = _identity(os.stat(self.name, dir_fd=self.parent_fd, follow_symlinks=False))
        self.directory_fd = os.open(self.name, _directory_flags(), dir_fd=self.parent_fd)
        if _check_directory(self.directory_fd, private=True) != self.directory_identity:
            raise AgentTaskError('macOS newly created directory identity changed')
        getattr(os, 'fchmod')(self.directory_fd, 0o700)
        self.directory_identity = _check_directory(self.directory_fd, private=True)
        connection.bind(self.address)
        self.socket_identity = _UnverifiedPath()
        self.socket_identity = _identity(os.stat(self.socket_name, dir_fd=self.directory_fd, follow_symlinks=False))
        os.chmod(self.socket_name, 0o600, dir_fd=self.directory_fd, follow_symlinks=False)
        self.socket_identity = _check_socket(self.directory_fd, self.socket_name)
        self._require_path()
        return DarwinEndpoint(self.directory, self.directory_identity, self.socket_name,
                              self.socket_identity, self_identity())

    def _require_path(self) -> None:
        """The path bound through must still lead to the directory retained by descriptor."""
        descriptor = _open_directory(self.directory)
        try:
            if _identity(os.fstat(descriptor)) != self.directory_identity:
                raise AgentTaskError('macOS endpoint path was replaced during bind')
        finally:
            _close_directory(descriptor)

    @property
    def address(self) -> str:
        """The absolute path; the retained directory is checked again after binding."""
        return socket_path(self.directory, self.socket_name)


class DarwinEndpointCheck(_EndpointCheck):
    """Open and check the trusted endpoint's directory before and after connecting."""

    def __init__(self, endpoint: DarwinEndpoint) -> None:  # pylint: disable=super-init-not-called
        # reason: the Linux initializer accepts only LinuxEndpoint; the checks it runs are the same.
        if not isinstance(endpoint, DarwinEndpoint) or endpoint.socket_name != SOCKET_NAME:
            raise AgentTaskError('macOS endpoint description is invalid')
        self.endpoint = endpoint  # type: ignore[assignment]
        self.descriptor = _open_directory(endpoint.directory)
        try:
            self.verify()
        except BaseException:
            self.close()
            raise

    @property
    def address(self) -> str:
        """Connect by the absolute path; ``verify`` runs again once connected."""
        return socket_path(self.endpoint.directory, self.endpoint.socket_name)
