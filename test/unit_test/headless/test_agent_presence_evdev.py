"""Wayland evdev presence: physical devices only, held keys, hotplug and fail-closed startup. No Qt."""
import os
import struct
import sys

import pytest

from je_auto_control.utils.agent_runtime import presence_evdev
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.presence_evdev import EvdevPresenceAPI, _physical_nodes
from je_auto_control.utils.agent_runtime.presence_evdev_grab import _WORD_BITS, UnannouncedKeys, virtual_remapper
from je_auto_control.utils.agent_runtime.presence_platform import default_presence_api

posix = pytest.mark.skipif(sys.platform == "win32", reason="select() takes only sockets on Windows")
EVENT = struct.Struct("@llHHi")


def event(kind, code, value):
    return EVENT.pack(0, 0, kind, code, value)


def test_wayland_sessions_get_the_evdev_source():
    assert isinstance(default_presence_api("linux", {"WAYLAND_DISPLAY": "wayland-0"}), EvdevPresenceAPI)


def test_no_readable_physical_device_refuses_to_start():
    source = EvdevPresenceAPI(lambda: True, nodes=lambda: ["/dev/input/event0"],
                              opener=lambda path: (_ for _ in ()).throw(PermissionError(13, "denied", path)))
    with pytest.raises(AgentTaskError, match="cannot read every"):
        source.open(lambda: None)
    with pytest.raises(AgentTaskError, match="cannot restart"):
        source.open(lambda: None)


@pytest.mark.skipif(sys.platform == "win32", reason="sysfs symlinks need POSIX")
def test_virtual_devices_such_as_uinput_are_left_out(tmp_path):
    devices, sysfs, root = tmp_path / "devices", tmp_path / "class", tmp_path / "input"
    for name, parent in (("event0", "platform/i8042/serio0/input/input0"), ("event1", "virtual/input/input7"),
                         ("event2", "virtual/misc/uhid/0005:046D:B342.0003/input/input9")):
        target = devices / parent
        target.mkdir(parents=True)
        (sysfs / name).mkdir(parents=True)
        os.symlink(target, sysfs / name / "device")
    root.mkdir()
    for name in ("event0", "event1", "event2", "mice"):
        (root / name).touch()
    # event2 is a Bluetooth keyboard (uhid): leaving it out would read its user as absent.
    assert _physical_nodes(str(root), str(sysfs)) == [str(root / "event0"), str(root / "event2")]


class Devices:
    def __init__(self):
        self.pipes, self.present, self.ioctl_error, self.down = {}, [], None, ()

    def add(self, path):
        read, write = os.pipe()
        os.set_blocking(read, False)
        self.pipes[path] = (read, write)
        self.present.append(path)

    def opener(self, path):
        return os.dup(self.pipes[path][0])

    def write(self, path, *events):
        os.write(self.pipes[path][1], b"".join(events))

    def ioctl(self, _descriptor, _request, state, _mutate):
        if self.ioctl_error is not None:
            raise self.ioctl_error
        for code in self.down:
            state[code // 8] |= 1 << code % 8
        return 0

    def close(self):
        for read, write in self.pipes.values():
            os.close(read)
            os.close(write)


@pytest.fixture
def devices(monkeypatch):
    owned = Devices()
    monkeypatch.setattr(presence_evdev, "importlib",
                        type("NoIoctl", (), {"import_module": staticmethod(lambda name: type(
                            "F", (), {"ioctl": staticmethod(lambda *a: owned.ioctl(*a))}))}))
    yield owned
    owned.close()


@posix
def test_physical_events_report_activity_and_held_keys(devices):
    devices.add("/dev/input/event0")
    calls, now = [], [0.0]
    source = EvdevPresenceAPI(lambda: True, nodes=lambda: list(devices.present), opener=devices.opener,
                              clock=lambda: now[0])
    source.open(lambda: calls.append(True))
    try:
        assert source.poll(0.01) == (True, False) and calls == []
        devices.write("/dev/input/event0", event(1, 30, 1), event(0, 0, 0))
        assert source.poll(0.05) == (True, True) and calls == [True]
        devices.write("/dev/input/event0", event(1, 30, 0), event(0, 0, 0))
        assert source.poll(0.05) == (True, False)
        devices.write("/dev/input/event0", event(0, 0, 0))
        source.poll(0.05)
        assert len(calls) == 2  # a lone SYN_REPORT is not input activity
    finally:
        source.close()


@posix
def test_hotplugged_devices_join_and_removed_ones_leave(devices):
    devices.add("/dev/input/event0")
    now = [0.0]
    source = EvdevPresenceAPI(lambda: False, nodes=lambda: list(devices.present), opener=devices.opener,
                              clock=lambda: now[0])
    calls = []
    source.open(lambda: calls.append(True))
    try:
        devices.add("/dev/input/event5")
        now[0] = 2.0
        devices.write("/dev/input/event5", event(2, 0, 3), event(0, 0, 0))
        assert source.poll(0.05) == (False, False) and calls == [True]
        devices.present.clear()
        now[0] = 4.0
        with pytest.raises(AgentTaskError, match="lost every physical input device"):
            source.poll(0.01)
    finally:
        source.close()


def test_poll_needs_a_bounded_timeout_and_an_open_source():
    source = EvdevPresenceAPI(lambda: True, nodes=lambda: [])
    with pytest.raises(AgentTaskError):
        source.poll(0.01)
    with pytest.raises(AgentTaskError):
        source.poll(1.0)


def test_having_no_device_at_all_refuses_to_start():
    with pytest.raises(AgentTaskError, match="needs read access"):
        EvdevPresenceAPI(lambda: True, nodes=lambda: []).open(lambda: None)


@posix
def test_one_unreadable_device_refuses_the_source_even_beside_a_readable_one(devices):
    devices.add("/dev/input/event0")

    def opener(path):
        if path.endswith("event1"):
            raise PermissionError(13, "denied", path)
        return devices.opener(path)
    source = EvdevPresenceAPI(lambda: True, nodes=lambda: ["/dev/input/event0", "/dev/input/event1"], opener=opener)
    with pytest.raises(AgentTaskError, match="cannot read every"):
        source.open(lambda: None)
    assert source._fds == {}


@posix
def test_a_device_unplugged_before_it_opens_is_skipped(devices):
    devices.add("/dev/input/event0")

    def opener(path):
        if path.endswith("event1"):
            raise FileNotFoundError(2, "gone", path)
        return devices.opener(path)
    source = EvdevPresenceAPI(lambda: True, nodes=lambda: ["/dev/input/event0", "/dev/input/event1"], opener=opener)
    source.open(lambda: None)
    source.close()


@posix
def test_plugging_a_device_in_and_dropped_events_both_count_as_activity(devices):
    devices.add("/dev/input/event0")
    calls, now = [], [0.0]
    source = EvdevPresenceAPI(lambda: True, nodes=lambda: list(devices.present), opener=devices.opener,
                              clock=lambda: now[0])
    source.open(lambda: calls.append(True))
    try:
        devices.add("/dev/input/event5")
        now[0] = 2.0
        source.poll(0.01)
        assert calls == [True]
        devices.write("/dev/input/event0", event(1, 30, 1), event(0, 0, 0))
        assert source.poll(0.05)[1] is True
        devices.write("/dev/input/event0", event(0, 3, 0))  # SYN_DROPPED: the key-up may have been discarded
        assert source.poll(0.05) == (True, False) and len(calls) == 3
        devices.write("/dev/input/event0", event(1, 30, 1), event(0, 0, 0))
        source.poll(0.05)
        devices.ioctl_error = OSError(5, "unreadable")
        devices.write("/dev/input/event0", event(0, 3, 0))
        with pytest.raises(AgentTaskError, match="key state"):  # unknown is never "nothing held"
            source.poll(0.05)
        devices.ioctl_error = None
    finally:
        source.close()


@posix
def test_after_dropped_events_the_kernel_key_state_wins_over_the_older_events_in_the_batch(devices):
    devices.add("/dev/input/event0")
    source = EvdevPresenceAPI(lambda: True, nodes=lambda: ["/dev/input/event0"], opener=devices.opener)
    source.open(lambda: None)
    try:
        devices.down = (30,)  # released in the batch, pressed again before the query, which discards that press
        devices.write("/dev/input/event0", event(0, 3, 0), event(1, 30, 0), event(0, 0, 0))
        assert source.poll(0.05) == (True, True)
    finally:
        source.close()


@posix
def test_an_unreadable_key_state_refuses_the_source_at_start(devices):
    devices.add("/dev/input/event0")
    devices.ioctl_error = OSError(5, "unreadable")
    source = EvdevPresenceAPI(lambda: True, nodes=lambda: ["/dev/input/event0"], opener=devices.opener)
    with pytest.raises(AgentTaskError, match="key state"):
        source.open(lambda: None)
    assert source._fds == {}


class Sysfs:
    """Event nodes with a device directory each, as sysfs lays them out."""

    def __init__(self, base):
        self.devices, self.sysfs, self.root = base / "devices", base / "class", base / "input"
        self.root.mkdir()

    def add(self, node, parent, name, ev, key="0"):
        target = self.devices / parent
        (target / "capabilities").mkdir(parents=True)
        (target / "name").write_text(name + "\n", encoding="utf-8")
        (target / "capabilities" / "ev").write_text(ev + "\n", encoding="utf-8")
        (target / "capabilities" / "key").write_text(key + "\n", encoding="utf-8")
        (self.sysfs / node).mkdir(parents=True)
        os.symlink(target, self.sysfs / node / "device")
        (self.root / node).touch()
        return target

    def remapper(self):
        return virtual_remapper(str(self.root), str(self.sysfs))


def mask(*bits):
    words = {}
    for bit in bits:
        words[bit // _WORD_BITS] = words.get(bit // _WORD_BITS, 0) | 1 << bit % _WORD_BITS
    return " ".join(format(words.get(index, 0), "x") for index in range(max(words), -1, -1))


sysfs_links = pytest.mark.skipif(sys.platform == "win32", reason="sysfs symlinks need POSIX")


@sysfs_links
@pytest.mark.parametrize("ev,key", [(mask(0, 1), mask(30)), (mask(0, 1), mask(0x110)), (mask(0, 1, 2), mask(0x110))])
def test_a_virtual_keyboard_or_pointer_refuses_the_source(tmp_path, ev, key):
    sysfs = Sysfs(tmp_path)
    sysfs.add("event0", "platform/i8042/serio0/input/input0", "AT keyboard", mask(0, 1), mask(30))
    assert sysfs.remapper() is False
    sysfs.add("event3", "virtual/input/input30", "keyd virtual keyboard", ev, key)
    assert sysfs.remapper() is True


@sysfs_links
@pytest.mark.parametrize("parent,name,ev,key", [
    ("virtual/input/input30", "Headset (AVRCP)", mask(0, 1), mask(200, 201)),       # media keys only
    ("virtual/input/input30", "Virtual gamepad", mask(0, 1, 3), mask(0x130)),       # no keys, no pointer
    ("virtual/input/input30", "ydotoold virtual device", mask(0, 1, 2), mask(30)),  # this project's injector
    ("virtual/misc/uhid/0005/input/input9", "Bluetooth keyboard", mask(0, 1), mask(30)),
])
def test_devices_a_remapper_cannot_be_do_not_refuse_the_source(tmp_path, parent, name, ev, key):
    sysfs = Sysfs(tmp_path)
    sysfs.add("event3", parent, name, ev, key)
    assert sysfs.remapper() is False


@sysfs_links
def test_a_virtual_device_that_cannot_be_read_refuses_the_source(tmp_path):
    sysfs = Sysfs(tmp_path)
    target = sysfs.add("event3", "virtual/input/input30", "x", mask(0, 1), "not hexadecimal")
    assert sysfs.remapper() is True
    (target / "name").unlink()
    assert sysfs.remapper() is True
    (sysfs.root / "event3").unlink()
    assert sysfs.remapper() is False


def test_a_remapper_refuses_to_start_and_stops_a_running_source():
    source = EvdevPresenceAPI(lambda: True, nodes=lambda: [], remapper=lambda: True)
    with pytest.raises(AgentTaskError, match="virtual keyboard or pointer"):
        source.open(lambda: None)


@posix
def test_a_remapper_started_later_stops_the_source(devices):
    devices.add("/dev/input/event0")
    present, now = [], [0.0]
    source = EvdevPresenceAPI(lambda: True, nodes=lambda: list(devices.present), opener=devices.opener,
                              clock=lambda: now[0], remapper=lambda: bool(present))
    source.open(lambda: None)
    try:
        source.poll(0.01)
        present.append(True)
        now[0] = 2.0
        with pytest.raises(AgentTaskError, match="virtual keyboard or pointer"):
            source.poll(0.01)
    finally:
        source.close()


@posix
def test_a_key_the_kernel_reports_without_an_event_is_activity_and_then_a_refusal(devices):
    devices.add("/dev/input/event0")
    calls, now = [], [0.0]
    source = EvdevPresenceAPI(lambda: True, nodes=lambda: list(devices.present), opener=devices.opener,
                              clock=lambda: now[0])
    source.open(lambda: calls.append(True))
    try:
        devices.down = (30,)
        source.poll(0.01)
        assert calls == [True]
        devices.down = ()  # already released: the person still was there
        now[0] = 0.05
        with pytest.raises(AgentTaskError, match="held by another program"):
            source.poll(0.01)
    finally:
        source.close()


@posix
def test_an_event_that_arrives_just_after_the_key_state_explains_it(devices):
    devices.add("/dev/input/event0")
    now = [0.0]
    source = EvdevPresenceAPI(lambda: True, nodes=lambda: list(devices.present), opener=devices.opener,
                              clock=lambda: now[0])
    source.open(lambda: None)
    try:
        devices.down = (30,)
        source.poll(0.01)
        devices.write("/dev/input/event0", event(1, 30, 1), event(0, 0, 0))
        now[0] = 0.05
        assert source.poll(0.01) == (True, True)
        devices.down = ()
        devices.write("/dev/input/event0", event(1, 30, 0), event(0, 0, 0))
        now[0] = 0.10
        assert source.poll(0.01) == (True, False)
    finally:
        source.close()


def test_unannounced_keys_settle_before_they_refuse_and_are_forgotten_with_their_device():
    keys = UnannouncedKeys()
    assert keys.check({("a", 1)}, set(), 0.0) == (False, True)
    assert keys.check(set(), set(), 0.01) == (False, True)
    assert keys.check(set(), set(), 0.03) == (True, True)
    keys.forget("a")
    assert keys.check(set(), set(), 9.0) == (False, False)
    assert keys.check({("a", 1)}, {("a", 1)}, 9.0) == (False, False)


def test_a_key_released_among_discarded_events_is_not_taken_for_a_grab(monkeypatch):
    path, now, queued = "/dev/input/event0", [0.0], []
    answers = [()]  # the key state each query in turn reports; the last one repeats

    def ioctl(_descriptor, _request, state, _mutate):
        for code in answers[0] if len(answers) == 1 else answers.pop(0):
            state[code // 8] |= 1 << code % 8

    def read(_descriptor, _size):
        if not queued:
            raise BlockingIOError
        return queued.pop(0)
    monkeypatch.setattr(presence_evdev.importlib, "import_module", lambda _name: type(
        "F", (), {"ioctl": staticmethod(ioctl)}))
    monkeypatch.setattr(presence_evdev.select, "select", lambda fds, *_rest: (fds if queued else [], [], []))
    source = EvdevPresenceAPI(lambda: True, nodes=lambda: [path], remapper=lambda: False, clock=lambda: now[0],
                              opener=lambda _path: os.open(os.devnull, os.O_RDONLY))
    source.open(lambda: None)
    try:
        with monkeypatch.context() as patched:
            patched.setattr(presence_evdev.os, "read", read)
            answers[:] = [(30,), ()]  # down before the round, up again by the query after SYN_DROPPED
            queued.append(event(0, 3, 0))
            assert source.poll(0.01) == (True, False)
            now[0] = 0.5
            assert source.poll(0.01) == (True, False)
    finally:
        source.close()
