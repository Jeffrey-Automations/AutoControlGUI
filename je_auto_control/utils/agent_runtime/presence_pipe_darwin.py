"""macOS presence transport behind the Windows pipe's interface; its endpoint arrives only through the owned launch.

As on Linux, a listener binds a fresh private socket and a client may trust it only
when its endpoint came through a trusted launch: the worker reports it in its owned
bootstrap reply and the broker hands it to :meth:`DarwinPresencePipe.use`. The
runtime directory is the per-user temporary directory (``confstr`` of
``CS_DARWIN_USER_TEMP_DIR``, else ``TMPDIR``), which macOS creates 0700 per account.
The byte pipe and listener wrappers are the Linux ones; only the channel differs.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import socket
from types import SimpleNamespace
from typing import Any, Mapping

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.presence_pipe_linux import (
    _FILE_FIELDS, LinuxBytePipe, LinuxPresenceListener, _closed_object, _whole,
)

PLATFORM_TAG = "darwin"
_PEER_FIELDS = ("pid", "uid", "gid", "birth")
_ENDPOINT_FIELDS = {"platform", "directory", "directory_identity", "socket_name", "socket_identity",
                    "listener_process"}


def is_darwin_wire(value: Any) -> bool:
    """Whether endpoint wire metadata is the macOS shape; the Linux shape carries no platform tag."""
    return isinstance(value, Mapping) and value.get("platform") == PLATFORM_TAG


def endpoint_to_wire(endpoint: Any) -> dict[str, Any]:
    """Serialize launch metadata for the owned bootstrap reply; nothing secret is in it."""
    return {"platform": PLATFORM_TAG, "directory": endpoint.directory, "socket_name": endpoint.socket_name,
            "directory_identity": {name: getattr(endpoint.directory_identity, name) for name in _FILE_FIELDS},
            "socket_identity": {name: getattr(endpoint.socket_identity, name) for name in _FILE_FIELDS},
            "listener_process": {name: getattr(endpoint.listener_process, name) for name in _PEER_FIELDS}}


def endpoint_from_wire(value: Any) -> Any:
    """Rebuild launch metadata with closed fields and bounded values; connect still verifies all of it."""
    # pylint: disable=import-outside-toplevel  # reason: the endpoint types load only when used
    from je_auto_control.utils.agent_runtime.presence_endpoint_darwin import SOCKET_NAME, DarwinEndpoint
    from je_auto_control.utils.agent_runtime.presence_endpoint_linux import FileIdentity
    from je_auto_control.utils.agent_runtime.presence_peer_darwin import DarwinPeerIdentity
    if not is_darwin_wire(value) or set(value) != _ENDPOINT_FIELDS:
        raise AgentTaskError("macOS presence endpoint fields are invalid")
    directory, name = _wire_path(value, SOCKET_NAME)
    identities = [FileIdentity(*(_whole(item[field], field) for field in _FILE_FIELDS))
                  for item in (_closed_object(value[key], _FILE_FIELDS, key)
                               for key in ("directory_identity", "socket_identity"))]
    peer = _closed_object(value["listener_process"], _PEER_FIELDS, "listener_process")
    listener = DarwinPeerIdentity(*(_whole(peer[field], field) for field in _PEER_FIELDS))
    if listener.pid == 0 or listener.birth == 0:
        raise AgentTaskError("macOS presence endpoint listener is invalid")
    return DarwinEndpoint(directory, identities[0], name, identities[1], listener)


def _wire_path(value: Mapping[str, Any], socket_name: str) -> tuple[str, str]:
    """An absolute directory short enough for ``sun_path`` and the one fixed socket name."""
    directory, name = value["directory"], value["socket_name"]
    if (not isinstance(directory, str) or not directory.startswith("/")
            or re.fullmatch(r"[A-Za-z0-9._/-]{1,90}", directory) is None or name != socket_name):
        raise AgentTaskError("macOS presence endpoint path is invalid")
    return directory, name


def runtime_directory(environ: Mapping[str, str] | None = None) -> str:
    """The per-user temporary directory, canonicalized; refused when absent or relative."""
    environ = os.environ if environ is None else environ
    value = None
    if "CS_DARWIN_USER_TEMP_DIR" in getattr(os, "confstr_names", {}):
        value = getattr(os, "confstr")("CS_DARWIN_USER_TEMP_DIR")
    value = value or environ.get("TMPDIR")
    if not value or not Path(value).is_absolute():
        raise AgentTaskError("macOS physical presence needs the per-user temporary directory")
    return os.path.realpath(value)


class DarwinPresenceListener(LinuxPresenceListener):
    """Accept authenticated channels on one fresh private endpoint."""

    @property
    def endpoint_wire(self) -> dict[str, Any]:
        """The launch metadata the owned bootstrap reply carries to the broker."""
        return endpoint_to_wire(self._listener.endpoint)


class DarwinPresencePipe:
    """The macOS factory behind the presence server and broker; the endpoint is never guessed."""

    def __init__(self, namespace: str | None = None, *, runtime: str | None = None) -> None:
        self._namespace = namespace
        self._runtime = runtime
        self._endpoint: Any = None

    def listen(self) -> DarwinPresenceListener:
        """Bind a fresh private endpoint under the per-user temporary directory."""
        # pylint: disable-next=import-outside-toplevel  # reason: the macOS socket modules load only on macOS
        from je_auto_control.utils.agent_runtime.presence_channel_darwin import DarwinListener
        runtime = self._runtime if self._runtime is not None else runtime_directory()
        return DarwinPresenceListener(DarwinListener.create(runtime))

    def use(self, endpoint_wire: Any) -> None:
        """Adopt the endpoint an owned worker reported; only the broker's launch path calls this."""
        self._endpoint = endpoint_from_wire(endpoint_wire)

    def connect_if_present(self) -> LinuxBytePipe | None:
        """No name to look up: until an owned launch reported an endpoint, there is none."""
        return self.connect() if self._endpoint is not None else None

    def connect(self) -> LinuxBytePipe:
        """Connect to the reported endpoint; ``DarwinChannel`` pins its actual listener process."""
        # pylint: disable-next=import-outside-toplevel  # reason: the macOS socket modules load only on macOS
        from je_auto_control.utils.agent_runtime.presence_channel_darwin import DarwinChannel
        if self._endpoint is None:
            raise AgentTaskError("physical presence endpoint does not exist")
        return LinuxBytePipe(DarwinChannel.connect(self._endpoint, timeout=1))


class DarwinPresenceSecurity:
    """Peer evidence from the connected socket's audit token, shaped like ``WindowsPresenceSecurity``."""

    def current(self) -> Any:
        """This process's identity; the handshake compares births, never bare process ids."""
        # pylint: disable-next=import-outside-toplevel  # reason: the macOS socket modules load only on macOS
        from je_auto_control.utils.agent_runtime.presence_peer_darwin import self_identity
        return SimpleNamespace(birth=self_identity().birth)

    def peer(self, descriptor: int, *, server: bool) -> Any:
        """Retain the connected peer of this exact descriptor; a duplicate is closed once retained."""
        # pylint: disable-next=import-outside-toplevel  # reason: the macOS socket modules load only on macOS
        from je_auto_control.utils.agent_runtime.presence_peer_darwin import retain_connected_peer
        del server  # the same evidence serves both ends of the connection
        duplicate = socket.socket(fileno=os.dup(descriptor))
        try:
            return retain_connected_peer(duplicate)
        finally:
            duplicate.close()
