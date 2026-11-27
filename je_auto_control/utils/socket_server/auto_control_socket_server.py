"""Threaded TCP command server that runs action JSON (binds 127.0.0.1 by default).

Protocol, one command per connection:

1. ``AUTH <token>\\n`` -- answered ``AUTH_OK\\n``. Required unless the server
   was started with ``require_auth=False``; see
   :mod:`~je_auto_control.utils.socket_server.socket_auth` for which tokens
   are accepted and where the server token is written.
2. The command: an action list as JSON (it may span lines), or
   ``quit_server``, ended by a newline.
3. The reply: one line per action result, then ``Return_Data_Over_JE``.

A refusal -- no ``AUTH`` line, a wrong token, a role that lacks the
command -- is one error line followed by ``Return_Data_Over_JE``, so a
client that reads to the marker always gets an answer.
"""
import json
import socket
import socketserver
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple

from je_auto_control.utils.executor.action_executor import execute_action
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.rbac.authorization import AuthorizationContext, authorization_scope
from je_auto_control.utils.rbac.policy import capability_for_route, denied_command_in
from je_auto_control.utils.rbac.users import Capability
from je_auto_control.utils.script_vars.execution import execution_scope
from je_auto_control.utils.socket_server.socket_auth import (
    AUTH_OK, AUTH_PREFIX, SocketAuth, SocketAuthResult, default_token_path, remove_token_file,
    write_token_file,
)

_RECV_CHUNK_BYTES = 8192
# Safety cap so a client that never sends the newline terminator can't make us
# buffer without bound. Generous enough for very large action scripts.
_MAX_COMMAND_BYTES = 8 * 1024 * 1024
_COMMAND_TERMINATOR = b"\n"
_END_OF_REPLY = b"Return_Data_Over_JE"
_AUTH_PREFIX_BYTES = AUTH_PREFIX.encode("ascii")
_MAX_AUTH_LINE_BYTES = 4096
#: From accepting the connection to ``AUTH_OK``, whatever the client sends.
_AUTH_DEADLINE_S = 10.0
#: Wrong tokens one connection may try before it is closed.
_MAX_AUTH_FAILURES = 3
_HANDLER_TIMEOUT_S = 30.0
#: Running an action list is what ``POST /execute`` is on the REST server.
_RUN_CAPABILITY = capability_for_route("POST", "/execute")
_QUIT_CAPABILITY = Capability.MANAGE_HOSTS
_REFUSALS = {
    "unauthorized": "authentication failed: unknown token",
    "locked_out": "authentication refused: too many failed attempts, try again later",
    "rate_limited": "authentication refused: too many attempts, try again later",
}


class _ConnectionReader:
    """One connection's bytes, read on demand; what follows a line is kept for the next read.

    ``deadline`` (a ``time.monotonic()`` value) bounds every read while it is
    set: before authentication a client that trickles bytes is dropped when
    it passes, not after one timeout per byte.
    """

    def __init__(self, request: Any) -> None:
        self._request = request
        self._buffer = b""
        self.at_eof = False
        self.deadline: Optional[float] = None

    def _receive(self) -> bytes:
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("socket authentication deadline passed")
            self._request.settimeout(min(remaining, _HANDLER_TIMEOUT_S))
        chunk = self._request.recv(_RECV_CHUNK_BYTES)
        self.at_eof = not chunk
        return chunk

    def starts_with_auth(self) -> bool:
        """Read just enough to tell whether the client opened with ``AUTH ``."""
        while (len(self._buffer) < len(_AUTH_PREFIX_BYTES) and _COMMAND_TERMINATOR not in self._buffer
               and not self.at_eof):
            self._buffer += self._receive()
        return self._buffer.startswith(_AUTH_PREFIX_BYTES)

    def read_line(self) -> Optional[str]:
        """The next line without its newline; ``None`` past the size cap or at EOF."""
        while _COMMAND_TERMINATOR not in self._buffer:
            if len(self._buffer) > _MAX_AUTH_LINE_BYTES or self.at_eof:
                return None
            self._buffer += self._receive()
        line, _, self._buffer = self._buffer.partition(_COMMAND_TERMINATOR)
        if len(line) > _MAX_AUTH_LINE_BYTES:
            return None
        return line.decode("utf-8", errors="replace").strip()

    def read_command(self) -> str:
        """Read one newline-terminated command, spanning as many TCP reads as needed.

        A single ``recv`` returns whatever one TCP segment carried, not the
        whole message, so a >8 KiB script was silently truncated and then
        failed to parse. Accumulate chunks until the command is complete (see
        :func:`_is_complete`), the peer half-closes (EOF), or the safety cap is hit.
        """
        data, self._buffer = self._buffer, b""
        while not (data.endswith(_COMMAND_TERMINATOR) and _is_complete(data)):
            if self.at_eof or len(data) >= _MAX_COMMAND_BYTES:
                break
            data += self._receive()
        # errors="replace": invalid UTF-8 then fails as bad JSON and is answered
        # with the error and the sentinel, instead of a UnicodeDecodeError that
        # escaped every handler here and dropped the client without a reply.
        return data.strip().decode("utf-8", errors="replace")


def _read_command(request: socket.socket) -> str:
    """Read one newline-terminated command from ``request``; see :meth:`_ConnectionReader.read_command`."""
    return _ConnectionReader(request).read_command()


def _is_complete(buffer: bytes) -> bool:
    """Whether a buffer ending in the terminator holds the whole command.

    A newline is also ordinary whitespace inside JSON, so stopping at the
    first one cut pretty-printed commands short ("Expecting value"). The
    command is complete when it parses, or when it fails before its end --
    malformed, answered with the error as before. It is still arriving when
    parsing fails exactly at the end of what has come so far.
    """
    text = buffer.strip().decode("utf-8", errors="replace")
    try:
        json.loads(text)
    except ValueError as error:
        position = getattr(error, "pos", None)
        return position is None or position < len(text)
    except RecursionError:
        # Too deep to parse: complete, and answered with the error. It used
        # to escape the read and drop the client without a reply.
        return True
    return True


def _close_server_async(server: socketserver.BaseServer) -> None:
    """Shut the server down and release its port, off the handler thread.

    必須另開執行緒:ThreadingMixIn.server_close() 會 join 所有 handler
    執行緒,若由 handler 自己呼叫就會 "cannot join current thread"。
    Must run on its own thread. shutdown() waits for the serve_forever loop,
    and ThreadingMixIn.server_close() joins every handler thread — including
    the one that asked to quit, which raises "cannot join current thread".

    server_close() is the part that actually frees the port: shutdown() only
    stops the accept loop, leaving the listening socket open, so a restart on
    the same port failed with EADDRINUSE / WinError 10048.
    """
    def _close() -> None:
        server.shutdown()
        server.server_close()

    threading.Thread(target=_close, name="ac-socket-close",
                     daemon=True).start()


def _wire_text(value: object) -> bytes:
    """``str(value)`` as UTF-8, a lone surrogate (an undecodable file name) escaped."""
    return str(value).encode("utf-8", errors="backslashreplace")


def _refusal_for(caller: Optional[AuthorizationContext], actions: Any) -> Optional[str]:
    """Why ``caller``'s role may not run ``actions``; ``None`` when it may (or there is no role)."""
    if caller is None:
        return None
    if not caller.allows(_RUN_CAPABILITY):
        return f"forbidden: running actions needs {_RUN_CAPABILITY!r}; role {caller.role!r} lacks it"
    denied = denied_command_in(actions, caller)
    if denied is None:
        return None
    return f"forbidden: {denied[0]} needs {denied[1]!r}; role {caller.role!r} lacks it"


class TCPServerHandler(socketserver.BaseRequestHandler):
    """Authenticate one connection, then run the one command it sends."""

    def handle(self) -> None:
        try:
            self.request.settimeout(_HANDLER_TIMEOUT_S)
            reader = _ConnectionReader(self.request)
            admitted, caller = self._admit(reader)
            if not admitted:
                return
            command_string = reader.read_command()
        except OSError as error:
            # The timeout bounds each read, not the command: a client that
            # stops sending is dropped after it, one that trickles bytes is
            # held until the size cap (before AUTH_OK, until the deadline).
            autocontrol_logger.info("socket command read dropped: %r", error)
            return
        self._serve(command_string, caller)

    def _admit(self, reader: _ConnectionReader) -> Tuple[bool, Optional[AuthorizationContext]]:
        """Authenticate the connection; ``(False, None)`` means it was refused and answered."""
        # A server object without a policy (built by hand) refuses every token.
        auth: Optional[SocketAuth] = getattr(self.server, "socket_auth", None)
        if auth is not None and not auth.require_auth:
            if reader.starts_with_auth():  # a current client of an opted-out server
                reader.read_line()
                self._send_line(AUTH_OK)
            return True, None
        reader.deadline = time.monotonic() + _AUTH_DEADLINE_S
        for _ in range(_MAX_AUTH_FAILURES):
            result = self._try_auth_line(reader, auth)
            if result is None:
                return False, None
            if result.ok:
                reader.deadline = None
                self.request.settimeout(_HANDLER_TIMEOUT_S)
                self._send_line(AUTH_OK)
                return True, result.context
            self._reply([_REFUSALS.get(result.verdict, _REFUSALS["unauthorized"])])
            if result.verdict != "unauthorized":
                return False, None
        autocontrol_logger.warning("socket client %s closed after %d failed AUTH attempts",
                                   self._client(), _MAX_AUTH_FAILURES)
        return False, None

    def _try_auth_line(self, reader: _ConnectionReader,
                       auth: Optional[SocketAuth]) -> Optional[SocketAuthResult]:
        """Check the next ``AUTH`` line; ``None`` when the connection is over (answered or gone)."""
        if not reader.starts_with_auth():
            # Read the unauthenticated command whole first: closing on unread
            # bytes resets the connection and the client loses this answer.
            if reader.read_command():
                autocontrol_logger.warning("socket client %s sent a command without AUTH", self._client())
                self._reply([f"authentication required: send '{AUTH_PREFIX}<token>' as the first line"])
            return None
        line = reader.read_line()
        if line is None:
            self._reply(["authentication failed: malformed AUTH line"])
            return None
        if auth is None:
            return SocketAuthResult("unauthorized")
        result = auth.check(self._client(), line[len(AUTH_PREFIX):].strip())
        if not result.ok:
            autocontrol_logger.warning("socket client %s AUTH refused: %s", self._client(), result.verdict)
        return result

    def _client(self) -> str:
        address = getattr(self, "client_address", None)
        return str(address[0]) if address else "?"

    def _send_line(self, text: str) -> None:
        self.request.sendall(_wire_text(text) + _COMMAND_TERMINATOR)

    def _reply(self, lines: Iterable[object]) -> None:
        """Send each line, then the end-of-reply marker."""
        for line in lines:
            self._send_line(str(line))
        self.request.sendall(_END_OF_REPLY + _COMMAND_TERMINATOR)

    def _serve(self, command_string: str, caller: Optional[AuthorizationContext]) -> None:
        # Not the text itself: it may carry a vault passphrase or secret, and
        # execute_action logs the parsed list with those masked.
        autocontrol_logger.info("command received: %d characters", len(command_string))
        try:
            if command_string == "quit_server":
                self._quit(caller)
                return
            execute_str = json.loads(command_string)
            refusal = _refusal_for(caller, execute_str)
            if refusal is not None:
                autocontrol_logger.warning("socket command refused for %s: %s",
                                           caller.user_id if caller else "?", refusal)
                self._reply([refusal])
                return
            # One command, one variable scope, served as the authenticated user.
            with authorization_scope(caller), execution_scope():
                execute_record = execute_action(execute_str)
            self._reply(execute_record.values())
        # AutoControlException is the base of every framework error: an
        # empty payload raises AutoControlActionNullException and an unknown
        # command AutoControlActionException. Missing it here killed the
        # handler thread, so the client saw a bare EOF with no error line or
        # terminator. sqlite3 and cv2 errors derive from Exception alone and
        # did the same. Always answer with the error + the
        # Return_Data_Over_JE sentinel below.
        except Exception as error:  # noqa: BLE001  # reason: whatever a command raised, the client must get its reply
            autocontrol_logger.error("socket command failed: %r", error)
            try:
                self._reply([error])
            except OSError as send_error:
                autocontrol_logger.error("send error reply failed: %r", send_error)

    def _quit(self, caller: Optional[AuthorizationContext]) -> None:
        """Stop the server, unless ``caller``'s role may not."""
        if caller is not None and not caller.allows(_QUIT_CAPABILITY):
            self._reply([f"forbidden: quit_server needs {_QUIT_CAPABILITY!r}; "
                         f"role {caller.role!r} lacks it"])
            return
        autocontrol_logger.info("Now quit server")
        _close_server_async(self.server)


class TCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Threaded TCP command server for AutoControl.

    ``daemon_threads`` so a stalled handler thread never blocks interpreter
    exit (and, with the per-handler read timeout, stalled clients are dropped
    rather than accumulating non-daemon threads).

    ``close_flag`` used to live here. It was written on quit_server and read
    by nobody in the tree — a dead flag standing in for the ``server_close()``
    that was actually missing. Ask the socket instead: ``server.socket``
    is closed once quit_server has run.

    ``socket_auth`` is the authentication policy; a server left without one
    refuses every connection. ``token_path`` is the file the server token was
    written to, removed again by :meth:`server_close`.
    """

    daemon_threads = True
    socket_auth: Optional[SocketAuth] = None
    token_path: Optional[Path] = None

    @property
    def token(self) -> Optional[str]:
        """The server token clients authenticate with; ``None`` without one."""
        return self.socket_auth.token if self.socket_auth is not None else None

    def server_close(self) -> None:
        """Release the port, then remove the token file if it is still this server's."""
        super().server_close()
        path, self.token_path = self.token_path, None
        if path is not None and self.token is not None:
            remove_token_file(path, self.token)


def _publish_token(auth: SocketAuth, token_path: Optional[Path], port: int) -> Optional[Path]:
    """Write the server token where local clients look for it; ``None`` when there is none."""
    if not auth.require_auth or auth.token is None:
        return None
    written = write_token_file(token_path or default_token_path(port), auth.token)
    autocontrol_logger.info("socket server token written to %s", written)
    return written


def _log_policy(auth: SocketAuth, host: str, port: int, token: Optional[str]) -> None:
    if not auth.require_auth:
        autocontrol_logger.warning(
            "socket server %s:%d runs WITHOUT authentication (require_auth=False): any process "
            "that can reach it runs any command, quit_server included", host, port)
    elif auth.rbac_enabled:
        autocontrol_logger.info("socket server %s:%d accepts RBAC user tokens only", host, port)
        if token is not None:
            autocontrol_logger.warning("socket server token ignored: RBAC accepts user tokens only")


def start_autocontrol_socket_server(host: str = "127.0.0.1", port: int = 9938, *,
                                    token: Optional[str] = None, require_auth: bool = True,
                                    token_path: Optional[Path] = None) -> TCPServer:
    """
    Start the AutoControl TCP command server.
    啟動 AutoControl TCP 指令伺服器。

    :param host: bind address; defaults to localhost for least privilege.
    :param port: TCP port to listen on (0 picks a free one).
    :param token: the server token; else ``$JE_AUTOCONTROL_SOCKET_TOKEN``,
        else a random one. Ignored under RBAC, where user tokens authenticate.
    :param require_auth: ``False`` is the legacy opt-out: no ``AUTH`` line,
        every connection trusted. Logged as a warning.
    :param token_path: where the server token is written (owner-only);
        defaults to ``~/.je_auto_control/socket_server_<port>.token``.
    """
    auth = SocketAuth.from_environment(token, require_auth=require_auth)
    server = TCPServer((host, port), TCPServerHandler)
    server.socket_auth = auth
    try:
        server.token_path = _publish_token(auth, token_path, server.server_address[1])
    except BaseException:
        server.server_close()
        raise
    _log_policy(auth, host, server.server_address[1], token)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    return server
