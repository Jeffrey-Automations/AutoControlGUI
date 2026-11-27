"""Retain macOS connected-process evidence only; no desktop session or input authority.

macOS has no pidfd. The connector is named by the socket's audit token (pid and
pid version, taken by the kernel at connect time), its lifetime is pinned by a
retained ``kqueue`` ``EVFILT_PROC``/``NOTE_EXIT`` watch, and its identity is the
boot-unique ``p_uniqueid`` that ``proc_pidinfo`` reports. The watch is registered
before the identity is read, and the pid version reported with that identity must
equal the token's, so a pid reused in between is refused rather than retained.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
import select
import socket
import struct
import sys
import threading
from typing import Any

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.presence_peer_linux import _RetirementUnconfirmed

_SOL_LOCAL = 0
_LOCAL_PEERPID = 0x002
_LOCAL_PEERTOKEN = 0x006
_TOKEN = struct.Struct('=8I')
_PROC_PIDTBSDINFO = 3
_PROC_PIDUNIQIDENTIFIERINFO = 17
_BSD_INFO_SIZE = 136
# struct proc_uniqidentifierinfo: p_uuid[16], p_uniqueid, p_puniqueid, p_idversion, reserved...
_UNIQUE = struct.Struct('=16sQQiI QQ')
# struct proc_bsdinfo: the first eleven 32-bit fields are flags, status, xstatus,
# pid, ppid, uid, gid, ruid, rgid, svuid and svgid.
_BSD_HEAD = struct.Struct('=11I')


@dataclass(frozen=True)
class DarwinPeerIdentity:
    """Private connector identity; no active-desktop or current-writer claim."""

    pid: int
    uid: int
    gid: int
    birth: int


class _LibProc:
    """The two ``libproc`` reads this module needs, behind one seam tests replace."""

    def __init__(self) -> None:
        if sys.platform != 'darwin':
            raise AgentTaskError('macOS connected-peer evidence is unavailable on this platform')
        library = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
        self._pidinfo: Any = library.proc_pidinfo
        self._pidinfo.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int)
        self._pidinfo.restype = ctypes.c_int

    def pidinfo(self, pid: int, flavor: int, size: int) -> bytes | None:
        """Return exactly ``size`` bytes, or None once the process no longer exists."""
        buffer = ctypes.create_string_buffer(size)
        written = self._pidinfo(pid, flavor, 0, buffer, size)
        if written == 0 and ctypes.get_errno() == 3:  # ESRCH
            return None
        if written != size:
            raise AgentTaskError('macOS connected-peer process information is unavailable')
        return buffer.raw


_LIBPROC: list[Any] = []


def _libproc() -> Any:
    if not _LIBPROC:
        _LIBPROC.append(_LibProc())
    return _LIBPROC[0]


def _unique(pid: int) -> tuple[int, int] | None:
    """``(p_uniqueid, p_idversion)`` of a live pid, or None if it has exited."""
    raw = _libproc().pidinfo(pid, _PROC_PIDUNIQIDENTIFIERINFO, _UNIQUE.size)
    if raw is None:
        return None
    _uuid, unique, _parent, version, _r2, _r3, _r4 = _UNIQUE.unpack(raw)
    if not 1 <= unique < (1 << 64):
        raise AgentTaskError('macOS connected-peer unique process identity is invalid')
    return unique, version & 0xFFFFFFFF


def _account(pid: int, uid: int, gid: int) -> bool:
    """Whether every BSD credential of a live pid is this account; False once it has exited."""
    raw = _libproc().pidinfo(pid, _PROC_PIDTBSDINFO, _BSD_INFO_SIZE)
    if raw is None:
        return False
    fields = _BSD_HEAD.unpack_from(raw)
    if fields[3] != pid:
        raise AgentTaskError('macOS connected-peer process information names another process')
    uids, gids = (fields[5], fields[7], fields[9]), (fields[6], fields[8], fields[10])
    if any(value != uid for value in uids) or any(value != gid for value in gids):
        raise AgentTaskError('macOS connected-peer credentials differ from the current account')
    return True


def _current_account() -> tuple[int, int]:
    return getattr(os, 'geteuid')(), getattr(os, 'getegid')()


def self_identity() -> DarwinPeerIdentity:
    """This process's identity, read the same way a connected peer's is."""
    pid = os.getpid()
    uid, gid = _current_account()
    unique = _unique(pid)
    if unique is None or not _account(pid, uid, gid):
        raise AgentTaskError('macOS current process identity is unavailable')
    return DarwinPeerIdentity(pid, uid, gid, unique[0])


def _token(connection: socket.socket) -> tuple[int, int, int, int]:
    """``(pid, pid_version, uid, gid)`` the kernel recorded for the connector."""
    if not isinstance(connection, socket.socket) or connection.family != getattr(socket, 'AF_UNIX'):
        raise AgentTaskError('macOS connected-peer evidence requires a connected Unix socket')
    if connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
        raise AgentTaskError('macOS connected-peer evidence requires a stream socket')
    connection.getpeername()
    values = _TOKEN.unpack(connection.getsockopt(_SOL_LOCAL, _LOCAL_PEERTOKEN, _TOKEN.size))
    _auid, euid, egid, ruid, rgid, pid, _asid, version = values
    peer_pid, = struct.unpack('=i', connection.getsockopt(_SOL_LOCAL, _LOCAL_PEERPID, 4))
    if pid <= 0 or peer_pid != pid or (euid, egid) != (ruid, rgid):
        raise AgentTaskError('macOS connected-peer credentials are unavailable')
    return pid, version, euid, egid


def _watch(pid: int) -> Any:
    queue = getattr(select, 'kqueue')()
    try:
        if os.get_inheritable(queue.fileno()):
            raise AgentTaskError('macOS connected-peer watch inheritance is unconfirmed')
        event = getattr(select, 'kevent')(pid, filter=getattr(select, 'KQ_FILTER_PROC'),
                              flags=getattr(select, 'KQ_EV_ADD') | getattr(select, 'KQ_EV_ENABLE'),
                              fflags=getattr(select, 'KQ_NOTE_EXIT'))
        queue.control([event], 0, 0)
        return queue
    except BaseException:
        queue.close()
        raise


def _exited(queue: Any) -> bool:
    events = queue.control(None, 4, 0)
    return any(event.fflags & getattr(select, 'KQ_NOTE_EXIT') for event in events)


class DarwinPeerProcess:
    """Own one exit watch on the original connector; never signal or reopen a PID."""

    def __init__(self, queue: Any, identity: DarwinPeerIdentity) -> None:
        self._queue: Any = queue
        self._exited = False
        self.identity = identity
        self._lock = threading.Lock()

    def alive(self) -> bool:
        """Check the retained exit watch and the current identity without granting input."""
        with self._lock:
            if self._queue is None or self._exited:
                return False
            try:
                if _exited(self._queue):
                    self._exited = True
                    return False
                value = self.identity
                unique = _unique(value.pid)
                if unique is None or not _account(value.pid, value.uid, value.gid):
                    self._exited = True
                    return False
                if unique[0] != value.birth:
                    raise AgentTaskError('macOS connected-peer identity has changed')
                return True
            except AgentTaskError:
                raise
            except (OSError, ValueError, struct.error):
                raise AgentTaskError('macOS connected-peer identity cannot be verified') from None

    def close(self) -> None:
        """Close the owned watch once."""
        with self._lock:
            queue, self._queue = self._queue, None
            if queue is not None:
                try:
                    queue.close()
                except OSError:
                    raise _RetirementUnconfirmed('macOS connected-peer watch retirement is unconfirmed') from None


def retain_connected_peer(connection: socket.socket) -> DarwinPeerProcess:
    """Retain the original live same-account connector of this exact socket."""
    if sys.platform != 'darwin':
        raise AgentTaskError('macOS connected-peer evidence is unavailable on this platform')
    queue = None
    try:
        pid, version, uid, gid = _token(connection)
        if (uid, gid) != _current_account():
            raise AgentTaskError('macOS connected-peer account is different')
        queue = _watch(pid)
        unique = _unique(pid)
        if unique is None or unique[1] != version or _exited(queue):
            raise AgentTaskError('macOS connected-peer process has retired or was replaced')
        if not _account(pid, uid, gid):
            raise AgentTaskError('macOS connected-peer process has retired')
        peer = DarwinPeerProcess(queue, DarwinPeerIdentity(pid, uid, gid, unique[0]))
        queue = None
        return peer
    except AgentTaskError:
        raise
    except (OSError, ValueError, struct.error):
        raise AgentTaskError('macOS connected-peer process evidence cannot be verified') from None
    finally:
        if queue is not None:
            queue.close()
