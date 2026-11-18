"""Perform HTTP(S) requests headlessly for first-class API action steps.

A small, dependency-free client built on the standard library, so the
package needs no ``requests`` dependency. Supports method, headers, a JSON
or raw body, basic/bearer auth, and an explicit timeout; it returns a
plain response dict (status / ok / headers / text / json / url) so that
non-2xx responses are inspectable rather than raised. Imports no
``PySide6`` and only allows http/https schemes (Bandit B310).
"""
import base64
import contextvars
import errno
import functools
import http.client
import json
import os
import select
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from je_auto_control.utils.exception.cancellation import cancellation_checkpoint
from je_auto_control.utils.http_headers import CREDENTIAL_HEADERS
from typing import IO, Any, Dict, Mapping, Optional

_REQUEST_STOPPED = "request stopped"

# NOSONAR python:S5332 — http is allow-listed deliberately (other schemes
# are rejected); plain http is required for internal/localhost endpoints.
_ALLOWED_SCHEMES = ("http://", "https://")  # NOSONAR python:S5332
_DEFAULT_TIMEOUT = 30.0
# The whole body is held in memory (and decoded, and parsed as JSON), so an
# endless or huge response used to exhaust memory.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024


def _validate_url(url: str) -> None:
    if not isinstance(url, str) or not url.lower().startswith(_ALLOWED_SCHEMES):
        raise ValueError(f"only http/https URLs are allowed, got {url!r}")


def _apply_auth(headers: Dict[str, str],
                auth: Optional[Mapping[str, Any]]) -> None:
    if not auth:
        return
    kind = str(auth.get("type", "")).lower()
    if kind == "bearer":
        headers["Authorization"] = f"Bearer {auth.get('token', '')}"
    elif kind == "basic":
        raw = f"{auth.get('username', '')}:{auth.get('password', '')}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    else:
        raise ValueError(f"unknown auth type: {auth.get('type')!r}")


def _build_headers(headers: Optional[Mapping[str, Any]], json_body: Any,
                   auth: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    result = {str(key): str(value) for key, value in (headers or {}).items()}
    has_content_type = any(key.lower() == "content-type" for key in result)
    if json_body is not None and not has_content_type:
        result["Content-Type"] = "application/json"
    _apply_auth(result, auth)
    return result


def _encode_body(json_body: Any, data: Any) -> Optional[bytes]:
    if json_body is not None:
        return json.dumps(json_body).encode("utf-8")
    if data is None:
        return None
    if isinstance(data, int):
        # bytes(5) is five NUL bytes, not "5".
        raise TypeError("data must be str or bytes, not int")
    return data.encode("utf-8") if isinstance(data, str) else bytes(data)


def _try_json(text: str) -> Any:
    try:
        return json.loads(text)
    # RecursionError: a reply nested thousands deep raised it out of every
    # http_request -- a server's body could crash the caller.
    except (ValueError, TypeError, RecursionError):
        return None


def _response_limit(value: Any = None) -> int:
    limit = MAX_RESPONSE_BYTES if value is None else value
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESPONSE_BYTES:
        raise ValueError('invalid HTTP response byte limit')
    return limit


def _read_response(response: Any, want_bytes: bool = False, *,
                   limit: Optional[int] = None) -> Dict[str, Any]:
    """The response as a dict; with ``want_bytes`` the undecoded body is ``content``."""
    limit = _response_limit(limit)
    raw_status: Any = getattr(response, "status", None)
    if raw_status is None:
        raw_status = getattr(response, "code", 0)
    status = int(raw_status)
    body = response.read(limit + 1)
    if len(body) > limit:
        raise urllib.error.URLError(
            f"response body exceeds {limit} bytes")
    text = body.decode("utf-8", errors="replace")
    raw_headers = getattr(response, "headers", None)
    headers, set_cookie = _collect_headers(raw_headers)
    result: Dict[str, Any] = {
        "status": status,
        "ok": 200 <= status < 400,
        "headers": headers,
        "set_cookie": set_cookie,
        "text": text,
        "json": _try_json(text),
        "url": getattr(response, "url", None),
    }
    if want_bytes:
        # Only on request: the dict is otherwise JSON-ready, and ``text`` has
        # already replaced whatever was not UTF-8.
        result["content"] = body
    return result


def _collect_headers(raw_headers: Any) -> "tuple[Dict[str, str], list[str]]":
    """Response headers with repeats joined, plus every ``Set-Cookie`` value.

    ``dict(headers.items())`` kept only the last of a repeated header, so a
    second ``Link`` or ``Set-Cookie`` silently replaced the first. Repeats
    are joined with ", " (RFC 9110 5.3) except ``Set-Cookie``, whose dates
    contain commas: it keeps its last value under ``headers`` and all of
    them in the list.
    """
    headers: Dict[str, str] = {}
    set_cookie: list[str] = []
    for name, value in (raw_headers.items() if raw_headers else []):
        if name.lower() == "set-cookie":
            set_cookie.append(value)
            headers[name] = value
        elif name in headers:
            headers[name] = f"{headers[name]}, {value}"
        else:
            headers[name] = value
    return headers, set_cookie


def build_call(url: str, method: str = "GET",
               headers: Optional[Mapping[str, Any]] = None,
               json_body: Any = None, data: Any = None,
               auth: Optional[Mapping[str, Any]] = None,
               timeout: float = _DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """Build a transport ``call`` dict (url/method/headers/body/timeout)."""
    _validate_url(url)
    return {
        "url": url, "method": str(method).upper(),
        "headers": _build_headers(headers, json_body, auth),
        "body": _encode_body(json_body, data), "timeout": float(timeout),
    }


class _CheckedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Apply the scheme allow-list and the egress policy to every redirect.

    Only the first URL used to be checked, so a server on an allowed host
    could redirect to any other host -- or to ``ftp://``.
    """

    def redirect_request(self, req: urllib.request.Request, fp: IO[bytes], code: int,  # noqa: D102
                         msg: str, headers: http.client.HTTPMessage,
                         newurl: str) -> Optional[urllib.request.Request]:
        from je_auto_control.utils.egress.egress_policy import get_egress_policy
        _validate_url(newurl)
        get_egress_policy().check(newurl)
        new_request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_request is not None and _origin(newurl) != _origin(req.full_url):
            # urllib carries every header over, so a redirect to another host
            # received the Authorization meant for this one -- and a redirect
            # from https to http on the same host sent it in the clear.
            for name in CREDENTIAL_HEADERS:
                # Request stores header names capitalize()d.
                new_request.remove_header(name.capitalize())
        return new_request


class _RefusingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Return a 3xx as the response instead of following it."""

    def redirect_request(self, req: urllib.request.Request, fp: IO[bytes], code: int,  # noqa: D102
                         msg: str, headers: http.client.HTTPMessage,
                         newurl: str) -> Optional[urllib.request.Request]:
        return None


def _origin(url: str) -> "tuple[str, str]":
    parts = urllib.parse.urlsplit(url)
    return parts.scheme.lower(), (parts.netloc or "").lower()


# How often a stoppable request looks at its stop and cancellation, and how long
# a stop waits for the request's thread to notice its sockets were shut.
_STOP_POLL_SECONDS = 0.1
_ABORT_WAIT_SECONDS = 1.0
_recording = threading.local()


class _Connections:
    """The connections one stoppable request opened, so a stop can shut their sockets.

    Shutting the socket ends a ``recv`` that is waiting for the reply at once,
    and the TCP handshake is waited for in slices that look at the stop
    (:func:`_connect_in_slices`); a connection that finishes connecting after
    the stop is shut before it sends anything. A name lookup already in
    progress cannot be interrupted: it ends on its own and its result is
    discarded.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._opened: list[Any] = []
        self._aborted = False

    def wrap(self, http_class: Any) -> Any:
        """A stand-in for ``http_class`` that records every connection it makes."""
        def make(*args: Any, **kwargs: Any) -> Any:
            connection = http_class(*args, **kwargs)
            connect = connection.connect

            def checked_connect() -> None:
                connect()
                if self._is_aborted():
                    _shut(connection)
                    raise urllib.error.URLError(_REQUEST_STOPPED)

            connection.connect = checked_connect
            # http.client opens its socket through this attribute (proxies included).
            connection._create_connection = functools.partial(_connect_in_slices, aborted=self._is_aborted)
            with self._lock:
                if self._aborted:
                    raise urllib.error.URLError(_REQUEST_STOPPED)
                self._opened.append(connection)
            return connection
        return make

    def _is_aborted(self) -> bool:
        with self._lock:
            return self._aborted

    def abort(self) -> None:
        """Shut every socket this request opened; later connections are refused."""
        with self._lock:
            self._aborted = True
            opened = list(self._opened)
        for connection in opened:
            _shut(connection)


# A non-blocking connect that has not finished yet reports one of these.
_CONNECTING = frozenset({0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 10035})  # 10035: WSAEWOULDBLOCK
# The readiness wait; a seam so a test can hold a connect open without a black-holed address.
_wait_writable = select.select


def _connect_in_slices(address: Any, timeout: Any = None, source_address: Any = None, *,
                       aborted: Any, make_socket: Any = socket.socket) -> socket.socket:
    """``socket.create_connection`` whose wait for the handshake looks at ``aborted`` every slice.

    The name lookup (``getaddrinfo``) still blocks. Each address is tried in
    turn, as ``create_connection`` does; the connected socket is handed back
    blocking, with ``timeout`` as its per-operation timeout again.
    """
    host, port = address[0], address[1]
    limit = timeout if isinstance(timeout, (int, float)) else socket.getdefaulttimeout()
    deadline = None if limit is None else time.monotonic() + limit
    failure: Optional[OSError] = None
    for family, kind, proto, _name, target in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
        sock = make_socket(family, kind, proto)
        try:
            if source_address:
                sock.bind(source_address)
            sock.setblocking(False)
            code = sock.connect_ex(target)
            if code not in _CONNECTING:
                raise OSError(code, os.strerror(code))
            if code != 0:
                _await_connect(sock, deadline, aborted)
            sock.settimeout(limit)
            return sock
        except urllib.error.URLError:
            sock.close()
            raise
        except OSError as error:
            sock.close()
            failure = error
    raise failure if failure is not None else OSError(f"no address for {host!r}")


def _await_connect(sock: Any, deadline: Optional[float], aborted: Any) -> None:
    while True:
        if aborted():
            raise urllib.error.URLError(_REQUEST_STOPPED)
        remaining = _STOP_POLL_SECONDS if deadline is None else min(_STOP_POLL_SECONDS, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("timed out")
        _readable, writable, failed = _wait_writable([], [sock], [sock], remaining)
        if writable or failed:
            code = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if code:
                raise OSError(code, os.strerror(code))
            return


def _shut(connection: Any) -> None:
    sock = getattr(connection, "sock", None)
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        return  # already closed or never connected: nothing left to wake


def _recorded(http_class: Any) -> Any:
    connections = getattr(_recording, "active", None)
    return http_class if connections is None else connections.wrap(http_class)


class _RecordingHTTPHandler(urllib.request.HTTPHandler):
    """``HTTPHandler`` whose connections a stoppable request on this thread can shut."""

    def do_open(self, http_class: Any, req: Any, **kwargs: Any) -> Any:  # noqa: D102
        return super().do_open(_recorded(http_class), req, **kwargs)


class _RecordingHTTPSHandler(urllib.request.HTTPSHandler):
    """``HTTPSHandler`` whose connections a stoppable request on this thread can shut."""

    def do_open(self, http_class: Any, req: Any, **kwargs: Any) -> Any:  # noqa: D102
        return super().do_open(_recorded(http_class), req, **kwargs)


_OPENER = urllib.request.build_opener(_CheckedRedirectHandler, _RecordingHTTPHandler, _RecordingHTTPSHandler)
_NO_REDIRECT_OPENER = urllib.request.build_opener(
    _RefusingRedirectHandler, _RecordingHTTPHandler, _RecordingHTTPSHandler)


def urllib_transport(call: Mapping[str, Any]) -> Dict[str, Any]:
    """The default live transport: perform a ``call`` with ``urllib``.

    A malformed reply (``http.client.HTTPException``: a garbage status
    line, a truncated body) is raised as ``urllib.error.URLError``, the
    ``OSError`` every other transport failure already arrives as. With
    ``call["follow_redirects"]`` false a 3xx comes back as the response;
    with ``call["want_bytes"]`` true the reply also carries the undecoded
    body as ``content`` (for binary downloads).
    """
    limit = _response_limit(call.get('max_response_bytes'))
    request = urllib.request.Request(
        call["url"], data=call.get("body"), method=call["method"],
        headers=dict(call.get("headers") or {}))
    opener = _OPENER if call.get("follow_redirects", True) else _NO_REDIRECT_OPENER
    want_bytes = bool(call.get("want_bytes", False))
    try:
        with opener.open(  # nosec B310 — scheme allow-listed, redirects too
                request, timeout=float(call.get("timeout", _DEFAULT_TIMEOUT))) \
                as response:
            return _read_response(response, want_bytes, limit=limit)
    except urllib.error.HTTPError as error:
        return _read_error_response(error, want_bytes, limit=limit)
    except http.client.HTTPException as error:
        raise urllib.error.URLError(f"malformed HTTP response: {error!r}") from error


def _read_error_response(error: urllib.error.HTTPError, want_bytes: bool = False, *,
                         limit: Optional[int] = None) -> Dict[str, Any]:
    """A 4xx / 5xx response, read and closed like any other.

    Read inside the ``except HTTPError`` clause, a truncated error body raised
    ``http.client.IncompleteRead`` past the clause below it -- no OSError, so
    it aborted the script -- and the response was never closed.
    """
    try:
        with error:
            return _read_response(error, want_bytes, limit=limit)
    except http.client.HTTPException as bad:
        raise urllib.error.URLError(f"malformed HTTP response: {bad!r}") from bad


def http_request(url: str, method: str = "GET",
                 headers: Optional[Mapping[str, Any]] = None,
                 json_body: Any = None, data: Any = None,
                 auth: Optional[Mapping[str, Any]] = None,
                 timeout: float = _DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """Perform an HTTP(S) request and return a response dict.

    ``json_body`` is serialised to JSON (setting Content-Type when absent);
    ``data`` sends a raw string/bytes body. ``auth`` is a dict such as
    ``{"type": "bearer", "token": ...}`` or
    ``{"type": "basic", "username": ..., "password": ...}``. Non-2xx/3xx
    responses are returned (with their body) rather than raised, so callers
    can assert on status codes.
    """
    return perform_call(build_call(url, method, headers, json_body, data, auth, timeout))


def perform_call(call: Mapping[str, Any]) -> Dict[str, Any]:
    """Send a :func:`build_call` dict after the egress-policy check.

    The one path every outbound request in the package should take, so the
    egress policy, the redirect checks and the malformed-reply handling apply
    to all of them. Set ``call["follow_redirects"] = False`` to get a 3xx back
    instead of following it.
    """
    from je_auto_control.utils.egress.egress_policy import get_egress_policy
    from je_auto_control.utils.exception.cancellation import current_cancellation_token
    from je_auto_control.utils.executor.run_control import current_stop_token
    get_egress_policy().check(call["url"])  # allow-all unless an operator locked it down
    # Inside a stoppable run or a cancellation scope (a script, an MCP call, a
    # GUI task) nothing is sent once it is stopped, a stop while the request is
    # out shuts its sockets and ends the call, and a reply that arrives after
    # the stop is not handed on. Outside both the call is one plain request.
    _checkpoints()
    if current_stop_token() is None and current_cancellation_token() is None:
        response = urllib_transport(call)
    else:
        response = _stoppable_transport(call)
    _checkpoints()
    return response


def _checkpoints() -> None:
    from je_auto_control.utils.executor.run_control import checkpoint
    cancellation_checkpoint()
    checkpoint()


def _stoppable_transport(call: Mapping[str, Any]) -> Dict[str, Any]:
    """``urllib_transport`` on a helper thread, waited on in slices that look at the stop."""
    connections = _Connections()
    outcome: Dict[str, Any] = {}
    done = threading.Event()
    context = contextvars.copy_context()

    def run() -> None:
        _recording.active = connections
        try:
            outcome["response"] = context.run(urllib_transport, call)
        except BaseException as error:  # NOSONAR python:S5754  # reason: handed to the waiting caller, which raises it
            outcome["error"] = error
        finally:
            _recording.active = None
            done.set()

    threading.Thread(target=run, name="http-request", daemon=True).start()
    while not done.wait(_STOP_POLL_SECONDS):
        try:
            _checkpoints()
        except BaseException:
            connections.abort()
            done.wait(_ABORT_WAIT_SECONDS)
            raise
    if "error" in outcome:
        raise outcome["error"]
    return outcome["response"]
