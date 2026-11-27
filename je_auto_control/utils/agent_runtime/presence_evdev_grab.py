"""Recognise hosts where another program may hold a physical input device for itself.

``EVIOCGRAB`` sends a device's events to the grabber alone, so a person using it looks absent.
Nothing reports a grab, and trying one takes the person's own input for a moment, so this never
does. It uses two facts that cost nothing to read. A key remapper (keyd, input-remapper) has to
give its output back through a ``uinput`` keyboard or pointer, so such a device refuses the source.
And the kernel's key state is the device's own: a key it reports down that no event announced means
the events went elsewhere. Motion on a device grabbed without any ``uinput`` output, as a virtual
machine's evdev passthrough can do, shows in neither.
"""
from __future__ import annotations

import os
import struct

VIRTUAL_INPUT = "/devices/virtual/input/"
_WORD_BITS = struct.calcsize("@l") * 8
_EV_KEY, _EV_REL = 1, 2
_KEY_A, _BTN_LEFT = 30, 0x110
_SETTLE_SECONDS = 0.02
# This project's own command-line injector; a remapper does not use its name.
_INJECTORS = frozenset({"ydotoold virtual device"})


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as stream:
        return stream.read(4096).strip()


def _bit(mask: str, number: int) -> bool:
    """A sysfs capability bitmap: hexadecimal words, the most significant first."""
    words = [int(word, 16) for word in mask.split()]
    index = number // _WORD_BITS
    return index < len(words) and bool(words[-1 - index] >> number % _WORD_BITS & 1)


def _types_or_points(device: str) -> bool:
    """Whether this device can act as a keyboard or pointer; media-key and gamepad devices cannot."""
    capabilities = os.path.join(device, "capabilities")
    kinds = _read(os.path.join(capabilities, "ev"))
    if _bit(kinds, _EV_REL):
        return True
    keys = _read(os.path.join(capabilities, "key")) if _bit(kinds, _EV_KEY) else "0"
    return _bit(keys, _KEY_A) or _bit(keys, _BTN_LEFT)


def _remaps(name: str, root: str, sysfs: str) -> bool:
    device = os.path.realpath(os.path.join(sysfs, name, "device"))
    if VIRTUAL_INPUT not in device + "/":
        return False
    try:
        return _read(os.path.join(device, "name")) not in _INJECTORS and _types_or_points(device)
    except (OSError, ValueError):
        return os.path.exists(os.path.join(root, name))  # unreadable, unless it just went away


def virtual_remapper(root: str = "/dev/input", sysfs: str = "/sys/class/input") -> bool:
    """Whether a ``uinput`` keyboard or pointer other than a known injector exists; unreadable counts as one."""
    try:
        names = os.listdir(root)
    except OSError:
        return False  # the source itself refuses a host without input nodes
    return any(_remaps(name, root, sysfs) for name in names if name.startswith("event") and name[5:].isdigit())


class UnannouncedKeys:
    """Find keys the kernel reports down that the device's own events never mentioned.

    A key's state bit is set just before its event reaches a reader, so one sighting proves
    nothing; a key still unmentioned a moment later does, even if it is up again by then.
    """

    def __init__(self) -> None:
        self._pending: dict[tuple[str, int], float] = {}

    def forget(self, path: str) -> None:
        """Drop what is pending for a device that left or whose events the kernel discarded."""
        self._pending = {item: since for item, since in self._pending.items() if item[0] != path}

    def check(self, down: set[tuple[str, int]], announced: set[tuple[str, int]], now: float) -> tuple[bool, bool]:
        """Return ``(grabbed, suspected)`` for the keys down before this round and those now known."""
        self._pending = {item: since for item, since in self._pending.items() if item not in announced}
        for item in down - announced:
            self._pending.setdefault(item, now)
        grabbed = any(now - since >= _SETTLE_SECONDS for since in self._pending.values())
        return grabbed, bool(self._pending)


__all__ = ["VIRTUAL_INPUT", "UnannouncedKeys", "virtual_remapper"]
