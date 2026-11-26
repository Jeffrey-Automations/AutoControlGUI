"""Client for the TCP socket server: authenticate, send one command, read the reply.

The token is the explicit ``token`` argument, else
``$JE_AUTOCONTROL_SOCKET_TOKEN``, else the server's token file for that port
(``~/.je_auto_control/socket_server_<port>.token``, or ``token_path``).
Under RBAC, pass the user's token. Standard library only; imports no ``PySide6``.
"""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any, BinaryIO, List, Optional

from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.socket_server.socket_auth import (
    AUTH_OK, AUTH_PREFIX, TOKEN_ENV, SocketAuthError, default_token_path, read_token_file,
    validate_token,
)

#: The line that ends every reply of the server.
END_OF_REPLY = "Return_Data_Over_JE"
_MAX_LINE_BYTES = 8 * 1024 * 1024


class SocketClientError(AutoControlException, ConnectionError):
    """The server closed the connection before it finished its reply."""


def read_socket_token(port: int = 9938, token_path: Optional[Path] = None) -> str:
    """The token a socket server on ``port`` wrote for local clients."""
    return read_token_file(token_path if token_path is not None else default_token_path(port))


def client_token(port: int, token: Optional[str] = None,
                 token_path: Optional[Path] = None) -> str:
    """``token``, else ``$JE_AUTOCONTROL_SOCKET_TOKEN``, else the token file for ``port``."""
    if token is not None:
        return validate_token(token)
    from_env = os.environ.get(TOKEN_ENV, "").strip()
    if from_env:
        return validate_token(from_env)
    return read_socket_token(port, token_path)


def _read_reply(stream: BinaryIO, *, allow_eof: bool = False) -> List[str]:
    """The lines before the end-of-reply marker; EOF first raises unless ``allow_eof``."""
    lines: List[str] = []
    while True:
        raw = stream.readline(_MAX_LINE_BYTES)
        if not raw:
            if allow_eof:
                return lines
            raise SocketClientError("the socket server closed the connection mid-reply")
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == END_OF_REPLY:
            return lines
        lines.append(line)


def authenticate_connection(connection: socket.socket, stream: BinaryIO, token: str) -> None:
    """Send ``AUTH <token>`` on ``connection``; raise :class:`SocketAuthError` unless accepted."""
    connection.sendall(f"{AUTH_PREFIX}{validate_token(token)}\n".encode("utf-8"))
    first = stream.readline(_MAX_LINE_BYTES).decode("utf-8", errors="replace").rstrip("\r\n")
    if first == AUTH_OK:
        return
    detail = [first, *_read_reply(stream, allow_eof=True)] if first else ["connection closed"]
    raise SocketAuthError("socket server refused the token: " + " ".join(detail).strip())


def send_socket_command(command: Any, host: str = "127.0.0.1", port: int = 9938, *,
                        token: Optional[str] = None, token_path: Optional[Path] = None,
                        require_auth: bool = True, timeout: float = 30.0) -> List[str]:
    """Send one command (an action list, or ``"quit_server"``); return the reply lines.

    ``require_auth=False`` talks to a server started with ``--no-auth`` the
    legacy way, without an ``AUTH`` line. The token is looked up only when
    it is needed.
    """
    payload = command if isinstance(command, str) else json.dumps(command)
    with socket.create_connection((host, port), timeout=timeout) as connection:
        with connection.makefile("rb") as stream:
            if require_auth:
                authenticate_connection(connection, stream, client_token(port, token, token_path))
            connection.sendall(payload.encode("utf-8") + b"\n")
            # quit_server is answered only when it is refused.
            return _read_reply(stream, allow_eof=payload.strip() == "quit_server")


__all__ = [
    "END_OF_REPLY", "SocketClientError", "authenticate_connection", "client_token",
    "read_socket_token", "send_socket_command",
]
