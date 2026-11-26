"""Connection admission for the TCP remote-desktop host: pending cap and auth deadline.

A connection is *pending* from the moment it is accepted until it proves
its credentials (token, share code, TOTP-bound token or resume token).
Pending connections have their own small cap, refused at accept, and one
deadline for the whole of the TLS handshake, the WebSocket upgrade and the
challenge-response; only a connection that authenticated takes one of the
host's ``max_clients`` viewer slots. Before this, a connection that never
answered held a viewer slot for up to 60 s, so a few silent sockets locked
every real viewer out.
"""
import math
import socket
import threading
import time
from functools import partial
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, cast

from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.remote_desktop.host_access import (
    _AUTH_TIMEOUT_S, _ip_in_allowlist,
)
from je_auto_control.utils.remote_desktop.host_client import _ClientHandler
from je_auto_control.utils.remote_desktop.transport import MessageChannel

if TYPE_CHECKING:
    import ssl

    from je_auto_control.utils.remote_desktop.host import RemoteDesktopHost

#: Connections still authenticating at once; beyond this new ones are closed at accept.
DEFAULT_MAX_PENDING_HANDSHAKES = 8
#: Seconds from accept to proven credentials (TLS, WebSocket upgrade, challenge-response).
DEFAULT_AUTH_TIMEOUT_S = 10.0
#: Shortest socket timeout handed to a pending read: zero would make the socket non-blocking.
_MIN_READ_TIMEOUT_S = 0.05
#: Pause after a failed accept(), so a lasting failure does not spin.
_ACCEPT_RETRY_S = 0.1


def validate_admission_args(max_pending_handshakes: Any, auth_timeout: Any) -> Tuple[int, float]:
    """Check both admission settings and return them as ``(int, float)``.

    The cap is a whole number of at least one; the deadline a finite number
    of seconds in ``(0, 60]``. The upper bound is the host's whole-handshake
    watchdog: a longer pending deadline would loosen it rather than tighten
    it. Booleans, strings and fractional caps are refused rather than
    coerced, because these values arrive from JSON action files and MCP calls.
    """
    if (isinstance(max_pending_handshakes, bool) or not isinstance(max_pending_handshakes, (int, float))
            or not float(max_pending_handshakes).is_integer() or max_pending_handshakes < 1):
        raise ValueError(f"max_pending_handshakes must be a whole number >= 1, got {max_pending_handshakes!r}")
    if (isinstance(auth_timeout, bool) or not isinstance(auth_timeout, (int, float))
            or not math.isfinite(auth_timeout) or not 0 < auth_timeout <= _AUTH_TIMEOUT_S):
        raise ValueError(f"auth_timeout must be in (0, {_AUTH_TIMEOUT_S:g}] seconds, got {auth_timeout!r}")
    return int(max_pending_handshakes), float(auth_timeout)


def close_socket(sock: socket.socket) -> None:
    """Shut ``sock`` down and close it, so a read blocked on it in another thread returns."""
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


class PendingAdmission:
    """One connection's passage from accept to a viewer slot, under one deadline.

    Holds one of the host's pending slots until :meth:`settle`. When the
    deadline passes first, or the host aborts it, whatever the connection
    currently is -- the raw socket, the TLS socket, the message channel --
    is closed, which ends the read the handshake thread is blocked in.
    """

    def __init__(self, slots: threading.BoundedSemaphore, deadline_s: float) -> None:
        self._slots = slots
        self._lock = threading.Lock()
        self._closer: Optional[Callable[[], None]] = None
        self._expired = False
        self._settled = False
        self._freed = False
        self._deadline = time.monotonic() + float(deadline_s)
        self._timer = threading.Timer(float(deadline_s), self.abort)
        self._timer.daemon = True
        self._timer.start()

    def remaining(self) -> float:
        """Seconds left before the deadline (never negative)."""
        return max(0.0, self._deadline - time.monotonic())

    def read_timeout(self) -> float:
        """Socket timeout for the next pending read: the time left, within the host's bound."""
        return max(_MIN_READ_TIMEOUT_S, min(_AUTH_TIMEOUT_S, self.remaining()))

    def watch(self, closer: Callable[[], None]) -> None:
        """Make ``closer`` what the deadline runs; runs it now when the deadline already passed."""
        with self._lock:
            if self._settled:
                return
            self._closer = closer
            expired = self._expired
        if expired:
            closer()

    def abort(self) -> None:
        """End the pending phase now: the deadline passed or the host is stopping."""
        with self._lock:
            if self._settled:
                return
            self._expired = True
            closer = self._closer
        if closer is not None:
            closer()

    def settle(self) -> bool:
        """Leave the pending phase: stop the deadline and free the pending slot (once).

        ``False`` when the deadline passed (or the host aborted) first, in
        which case the connection was already closed and must not be admitted.
        """
        self._timer.cancel()
        with self._lock:
            self._settled = True
            self._closer = None
            expired = self._expired
            release, self._freed = not self._freed, True
        if release:
            self._slots.release()
        return not expired


def _close_quietly(sock: socket.socket) -> None:
    try:
        sock.close()
    except OSError:
        pass


class ConnectionAdmissionMixin:
    """Accept-to-authenticated half of :class:`RemoteDesktopHost`.

    The accept loop, the per-connection handshake thread and the two
    admission checks: a pending slot at accept, and a viewer slot once
    the credentials verified. Requires the host to provide the attributes
    declared below plus ``_build_channel`` and ``_reap_dead_clients``.
    """

    if TYPE_CHECKING:
        # Declared, never defined: the host class this is mixed into owns them.
        _clients: List[_ClientHandler]
        _clients_lock: threading.Lock
        _pending: Dict[PendingAdmission, threading.Event]
        _handshake_slots: threading.BoundedSemaphore
        _max_clients: int
        _auth_timeout: float
        _listen_sock: Optional[socket.socket]
        _ssl_context: Optional["ssl.SSLContext"]
        _ip_allowlist: Optional[List[Any]]

        def _build_channel(self, sock: socket.socket, address: Tuple[Any, ...]) -> MessageChannel:
            ...

    def _ip_allowed(self, address: Tuple[Any, ...]) -> bool:
        """Apply the Phase 4.3 allowlist; log + reject silently otherwise."""
        peer_ip = address[0] if address else ""
        if _ip_in_allowlist(self._ip_allowlist, peer_ip):
            return True
        autocontrol_logger.info("remote_desktop blocked %s by ip_allowlist", peer_ip)
        return False

    def _accept_loop(self, stop: threading.Event) -> None:
        # The timeout is set by start() on the owning thread, before the socket
        # is published: calling settimeout() here would race a concurrent
        # stop() closing it and raise WSAENOTSOCK outside any handler.
        listen = self._listen_sock
        if listen is None:
            return
        while not stop.is_set():
            try:
                client_sock, address = listen.accept()
            except socket.timeout:
                continue
            except OSError as error:
                if stop.is_set() or listen.fileno() == -1:
                    return
                # A connection aborted before it was accepted, or no file
                # descriptor left: returning here left a host that reads as
                # running and takes nobody.
                autocontrol_logger.info("remote_desktop accept failed: %r", error)
                stop.wait(_ACCEPT_RETRY_S)
                continue
            if not self._ip_allowed(address):
                _close_quietly(client_sock)
                continue
            self._spawn_handshake(client_sock, address, stop)

    def _spawn_handshake(self, client_sock: socket.socket, address: Tuple[Any, ...],
                         stop: threading.Event) -> None:
        """Hand a connection a pending slot and its own thread, or close it.

        The TLS handshake, the WS upgrade and authentication used to run on
        the one accept thread, where a slow peer kept every other viewer
        from connecting; each connection now has its own thread, and at
        most ``max_pending_handshakes`` of them are still authenticating.
        """
        if not self._handshake_slots.acquire(blocking=False):
            autocontrol_logger.info(
                "remote_desktop dropping %s: too many connections still authenticating", address,
            )
            _close_quietly(client_sock)
            return
        admission = PendingAdmission(self._handshake_slots, self._auth_timeout)
        try:
            threading.Thread(
                target=self._handshake, args=(client_sock, address, stop, admission),
                name="rd-handshake", daemon=True,
            ).start()
        except RuntimeError as error:   # no thread left to run it
            autocontrol_logger.warning("remote_desktop dropping %s: %r", address, error)
            admission.settle()
            _close_quietly(client_sock)

    def _handshake(self, client_sock: socket.socket, address: Tuple[Any, ...],
                   stop: threading.Event, admission: PendingAdmission) -> None:
        """Open the channel and authenticate the connection, all under its pending deadline."""
        try:
            if not self._track_pending(admission, address, stop):
                _close_quietly(client_sock)
                return
            client_sock.settimeout(admission.read_timeout())
            admission.watch(partial(close_socket, client_sock))
            wrapped = self._maybe_wrap_tls(client_sock, address, admission)
            if wrapped is None:
                return
            admission.watch(partial(close_socket, wrapped))
            channel = self._open_channel(wrapped, address)
            if channel is None:
                return
            admission.watch(channel.close)
            host = cast("RemoteDesktopHost", self)
            _ClientHandler(host, channel, address, admission=admission).start()
        finally:
            admission.settle()
            with self._clients_lock:
                self._pending.pop(admission, None)

    def _track_pending(self, admission: PendingAdmission, address: Tuple[Any, ...],
                       stop: threading.Event) -> bool:
        """Record a pending connection unless the host stopped or every viewer slot is taken."""
        # Prune handlers whose viewer already disconnected *before* the
        # capacity check below. Otherwise a client table filled with
        # max_clients dead handlers rejects every new connection forever.
        self._reap_dead_clients()
        with self._clients_lock:
            # Under the lock stop() snapshots and clears the tables with.
            if stop.is_set():
                autocontrol_logger.info("remote_desktop dropping %s: host stopped", address)
                return False
            if len(self._clients) >= self._max_clients:
                autocontrol_logger.info("remote_desktop dropping %s: max_clients reached", address)
                return False
            self._pending[admission] = stop
        return True

    def _admit_client(self, handler: _ClientHandler) -> bool:
        """Move a connection whose credentials verified from pending to a viewer slot.

        ``False`` -- and no slot -- when its deadline passed, the host
        stopped (or restarted) since it was accepted, or every viewer slot
        was taken meanwhile. A handler that never went through the accept
        path has no pending record and is refused too.
        """
        admission = handler.admission
        if admission is None or not admission.settle():
            return False
        self._reap_dead_clients()
        with self._clients_lock:
            # A stop() during the handshake sets the run's event, then clears
            # _pending under this lock: a handler admitted after that would
            # never be stopped -- input dispatched to a host already stopped.
            stop = self._pending.pop(admission, None)
            if stop is None or stop.is_set():
                autocontrol_logger.info("remote_desktop dropping %s: host stopped during handshake",
                                        handler.address)
                return False
            if len(self._clients) >= self._max_clients:
                autocontrol_logger.info("remote_desktop dropping %s: max_clients reached", handler.address)
                return False
            self._clients.append(handler)
        return True

    def _open_channel(self, sock: socket.socket,
                      address: Tuple[Any, ...]) -> Optional[MessageChannel]:
        """WS/TCP channel over an accepted (maybe TLS) socket. Closes the socket on failure."""
        try:
            return self._build_channel(sock, address)
        except (OSError, RuntimeError) as error:
            autocontrol_logger.info(
                "remote_desktop channel handshake from %s failed: %r", address, error,
            )
            _close_quietly(sock)
            return None

    def _maybe_wrap_tls(self, client_sock: socket.socket, address: Tuple[Any, ...],
                        admission: PendingAdmission) -> Optional[socket.socket]:
        """Return a TLS-wrapped socket when an ssl_context is configured.

        The handshake is run explicitly, after the deadline watches the TLS
        socket: wrapping detaches the raw socket, so closing that one would
        no longer end a handshake a silent peer never finishes.
        """
        if self._ssl_context is None:
            return client_sock
        wrapped: Optional["ssl.SSLSocket"] = None
        try:
            wrapped = self._ssl_context.wrap_socket(
                client_sock, server_side=True, do_handshake_on_connect=False,
            )
            admission.watch(partial(close_socket, wrapped))
            wrapped.settimeout(admission.read_timeout())
            wrapped.do_handshake()
            return wrapped
        except OSError as error:
            autocontrol_logger.info("remote_desktop TLS handshake from %s failed: %r", address, error)
            close_socket(wrapped if wrapped is not None else client_sock)
            return None

    def _reap_dead_clients(self) -> None:
        with self._clients_lock:
            self._clients = [c for c in self._clients if not c._shutdown.is_set()]


__all__ = [
    "DEFAULT_AUTH_TIMEOUT_S", "DEFAULT_MAX_PENDING_HANDSHAKES",
    "ConnectionAdmissionMixin", "PendingAdmission", "close_socket", "validate_admission_args",
]
