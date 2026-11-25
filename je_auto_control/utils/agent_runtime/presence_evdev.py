"""Wayland physical presence: kernel evdev devices that are not virtual, plus logind lock state.

A Wayland client sees no global input, and input the compositor receives through
libei never reaches evdev at all. The source therefore reads ``/dev/input/event*``
directly (the ``input`` group, or an equivalent ACL, grants it) and leaves out only
devices whose sysfs node is under ``/devices/virtual/input/``: every ``uinput``
device, which is how ``ydotool`` and similar injectors create input, lives there.
Other virtual parents stay in: Bluetooth keyboards and mice are ``uhid`` devices
under ``/devices/virtual/misc/uhid/``, and counting something a program injected as
a person only delays a task, while missing a person would let it take over.

Missing activity is never read as idleness. A physical device this account cannot
read refuses the source (at start, or when it is plugged in), a device appearing or
disappearing counts as activity, and a dropped-event marker (``SYN_DROPPED``) counts
as activity and re-reads which keys are held; a key state that cannot be read refuses
the source. Seat usability comes from the same logind query the X11 source uses.

This is a host trust decision, not a sandbox: an account that may write evdev
nodes or create kernel input drivers can still forge physical input. A key remapper
that grabs a device (``EVIOCGRAB``: keyd, input-remapper) hides it: the kernel then
delivers its events to the grabber alone, whose own output is a ``uinput`` device.
Do not use this source on such a host.
"""
from __future__ import annotations

import errno
import importlib
import os
import select
import struct
import threading
import time
from typing import Any, Callable

from je_auto_control.utils.agent_runtime.errors import AgentControlBusy, AgentTaskError
from je_auto_control.utils.agent_runtime.presence_platform import require_poll_timeout

_EVENT = struct.Struct("@llHHi")  # struct input_event: timeval, type, code, value
_EV_SYN, _EV_KEY, _EV_REL, _EV_ABS = 0, 1, 2, 3
_SYN_DROPPED = 3
_ACTIVITY = frozenset((_EV_KEY, _EV_REL, _EV_ABS))
_KEY_BYTES = 96  # KEY_MAX (0x2ff) + 1 bits
_EVIOCGKEY = (2 << 30) | (_KEY_BYTES << 16) | (ord("E") << 8) | 0x18
_RESCAN_SECONDS = 1.0
_DRAIN_LIMIT = 4096
_UINPUT = "/devices/virtual/input/"


def _physical_nodes(root: str = "/dev/input", sysfs: str = "/sys/class/input") -> list[str]:
    """Every event node except ``uinput`` devices; an unresolvable node stays in."""
    try:
        names = sorted(name for name in os.listdir(root) if name.startswith("event") and name[5:].isdigit())
    except OSError:
        return []
    return [os.path.join(root, name) for name in names
            if _UINPUT not in os.path.realpath(os.path.join(sysfs, name, "device")) + "/"]


class EvdevPresenceAPI:
    """Own the readable physical evdev nodes on one helper thread."""

    def __init__(self, interactive: Callable[[], bool] | None = None, *,
                 nodes: Callable[[], list[str]] = _physical_nodes,
                 opener: Callable[[str], int] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if interactive is None:
            # pylint: disable-next=import-outside-toplevel  # reason: shares the X11 source's logind query
            from je_auto_control.utils.agent_runtime.presence_x11 import LogindSession
            interactive = LogindSession().interactive
        self._interactive, self._nodes, self._clock = interactive, nodes, clock
        self._opener = opener if opener is not None else (
            lambda path: os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK") | getattr(os, "O_CLOEXEC")))
        self._fds: dict[str, int] = {}
        self._held: set[tuple[str, int]] = set()
        self._physical: Callable[[], None] | None = None
        self._thread: int | None = None
        self._scanned = 0.0
        self._changed = False
        self._closed = False

    def _owner(self) -> None:
        if self._thread is not None and self._thread != threading.get_ident():
            raise AgentTaskError("physical presence devices belong to a different thread")

    def open(self, physical: Callable[[], None]) -> None:
        """Open every physical device; one that cannot be read, or none at all, means no trusted source."""
        if self._thread is not None or self._closed:
            raise AgentTaskError("physical presence observer cannot restart")
        self._thread, self._physical = threading.get_ident(), physical
        try:
            self._rescan()
            if not self._fds:
                raise AgentTaskError("Wayland physical presence needs read access to a physical /dev/input device")
        except BaseException:
            self.close()
            raise
        self._changed = False  # the devices found at start are the baseline, not a change

    def _rescan(self) -> None:
        current = set(self._nodes())
        for path in [path for path in self._fds if path not in current]:
            self._drop(path)
        for path in sorted(current - set(self._fds)):
            try:
                descriptor = self._opener(path)
            except OSError as error:
                if error.errno in (errno.ENOENT, errno.ENODEV, errno.ENXIO):
                    continue  # unplugged between the listing and the open
                # A person could be using a device this source cannot see.
                raise AgentTaskError("Wayland physical presence cannot read every physical input device") from None
            self._fds[path] = descriptor
            self._changed = True
            if not self._seed_held(path, descriptor):
                self._drop(path)
        self._scanned = self._clock()

    def _seed_held(self, path: str, descriptor: int) -> bool:
        """Replace this device's held keys with the kernel's own answer; False when the device is gone.

        No event announces a key already down, and the query also removes key events still queued
        for this descriptor, so it must follow everything read so far, never precede it.
        """
        try:
            state = bytearray(_KEY_BYTES)
            importlib.import_module("fcntl").ioctl(descriptor, _EVIOCGKEY, state, True)
        except OSError as error:
            if error.errno == errno.ENODEV:
                return False
            raise AgentTaskError("Wayland physical presence cannot read a device's key state") from None
        self._held = {item for item in self._held if item[0] != path}
        for index, byte in enumerate(state):
            for bit in range(8):
                if byte >> bit & 1:
                    self._held.add((path, index * 8 + bit))
        return True

    def _drop(self, path: str) -> None:
        descriptor = self._fds.pop(path)
        self._changed = True
        self._held = {item for item in self._held if item[0] != path}
        try:
            os.close(descriptor)
        except OSError:
            pass  # the node is gone; its descriptor no longer names an open device

    def _read(self, path: str) -> bool:
        """Consume pending events of one device; True when any of them was input activity."""
        active = False
        for _index in range(_DRAIN_LIMIT):
            dropped = False
            try:
                raw = os.read(self._fds[path], _EVENT.size * 64)
            except BlockingIOError:
                return active
            except OSError as error:
                if error.errno in (errno.ENODEV, errno.EIO):
                    self._drop(path)
                    return active
                raise
            if not raw:
                return active
            for offset in range(0, len(raw) - len(raw) % _EVENT.size, _EVENT.size):
                _seconds, _micro, kind, code, value = _EVENT.unpack_from(raw, offset)
                dropped |= kind == _EV_SYN and code == _SYN_DROPPED
                active |= self._event(path, kind, code, value)
            if dropped and not self._seed_held(path, self._fds[path]):
                self._drop(path)
                return True
        raise AgentControlBusy("physical presence input queue is still active")

    def _event(self, path: str, kind: int, code: int, value: int) -> bool:
        if kind == _EV_SYN:
            return code == _SYN_DROPPED  # the kernel discarded events this source never saw
        if kind == _EV_KEY:
            if value:
                self._held.add((path, code))
            else:
                self._held.discard((path, code))
        return kind in _ACTIVITY

    def poll(self, timeout: float) -> tuple[bool, bool]:
        """Drain bounded device events, then report whether the seat is usable and anything is held."""
        self._owner()
        require_poll_timeout(timeout)
        if self._closed or self._thread is None:
            raise AgentTaskError("physical presence observer is unavailable")
        if self._clock() - self._scanned >= _RESCAN_SECONDS:
            self._rescan()
        if not self._fds:
            raise AgentTaskError("Wayland physical presence lost every physical input device")
        active = self._drain_ready(timeout)
        changed, self._changed = self._changed, False
        if active or changed:
            if self._physical is None:
                raise AgentTaskError("physical presence callback is unavailable")
            self._physical()
        return self._interactive(), bool(self._held)

    def _drain_ready(self, timeout: float) -> bool:
        readable, _write, _error = select.select(list(self._fds.values()), [], [], timeout)
        by_fd = {descriptor: path for path, descriptor in self._fds.items()}
        active = False
        for descriptor in readable:
            if by_fd.get(descriptor) in self._fds:
                active |= self._read(by_fd[descriptor])
        return active

    def close(self) -> None:
        """Close every owned device descriptor."""
        self._owner()
        self._closed = True
        for path in list(self._fds):
            self._drop(path)


def evdev_presence_api() -> Any:
    """The Wayland source; nothing opens until ``open``."""
    return EvdevPresenceAPI()
