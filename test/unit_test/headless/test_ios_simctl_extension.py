"""iOS Simulator extension over a fake ``xcrun simctl``: install, files, pasteboard, recording. No Xcode, no Qt."""
import json
import os
import signal
import subprocess  # nosec B404  # reason: only its TimeoutExpired is raised; nothing is started
from types import SimpleNamespace

import pytest

from je_auto_control.ios import simctl
from je_auto_control.ios.simctl import SimctlExtension, list_ios_simulators, use_ios_simulator
from je_auto_control.wrapper.device_context import DeviceError, DeviceTimeoutError, DeviceUnsupportedError

UDID = "0123ABCD-0123-4567-89AB-0123456789AB"


@pytest.fixture(autouse=True)
def recordings(monkeypatch):
    owned = {}
    monkeypatch.setattr(simctl, "_RECORDINGS", owned)
    return owned


class Simctl:
    def __init__(self, container):
        self.calls, self.container, self.pasteboard = [], str(container), ""

    def __call__(self, argv, **options):
        assert argv[:2] == ["xcrun", "simctl"] and options["shell"] is False and options["timeout"] > 0
        self.calls.append(argv[2:])
        verb = argv[2]
        if verb == "get_app_container":
            return SimpleNamespace(returncode=0, stdout=self.container + "\n")
        if verb == "pbpaste":
            return SimpleNamespace(returncode=0, stdout=self.pasteboard)
        if verb == "pbcopy":
            self.pasteboard = options["input"]
        return SimpleNamespace(returncode=0, stdout="")


class Recorder:
    def __init__(self, argv, **_options):
        self.argv, self.signals, self.code = argv, [], None
        open(argv[-1], "wb").write(b"mp4")

    def poll(self):
        return self.code

    def send_signal(self, value):
        self.signals.append(value)
        self.code = 0

    def wait(self, timeout):
        return self.code


@pytest.fixture
def extension(tmp_path):
    container = tmp_path / "container"
    container.mkdir()
    runner = Simctl(container)
    recorders = []

    def popen(argv, **options):
        recorders.append(Recorder(argv, **options))
        return recorders[-1]
    return SimctlExtension(UDID, runner=runner, popen=popen, available=lambda: True), runner, container, recorders


def test_capabilities_are_answered_without_running_simctl(extension):
    ext, runner, _container, _recorders = extension
    assert all(ext.capability(feature).available for feature in ("install", "files", "clipboard", "recording"))
    assert runner.calls == []
    missing = SimctlExtension(UDID, runner=runner, available=lambda: False)
    assert missing.capability("install").state == "needs_dependency"
    with pytest.raises(DeviceUnsupportedError):
        missing.install_app("App.app")


def test_install_needs_a_built_app_bundle(extension, tmp_path):
    ext, runner, _container, _recorders = extension
    bundle = tmp_path / "Demo.app"
    bundle.mkdir()
    assert ext.install_app(str(bundle)) == os.path.realpath(bundle)
    assert runner.calls[-1] == ["install", UDID, os.path.realpath(bundle)]
    with pytest.raises(DeviceError):
        ext.install_app(str(tmp_path / "Demo.ipa"))


def test_files_stay_inside_the_apps_data_container(extension, tmp_path):
    ext, _runner, container, _recorders = extension
    source = tmp_path / "in.txt"
    source.write_text("hello", encoding="utf-8")
    pushed = ext.push_file(str(source), "org.example.app:Documents/in.txt")
    assert open(pushed, encoding="utf-8").read() == "hello" and pushed.startswith(os.path.realpath(container))
    out = tmp_path / "out.txt"
    ext.pull_file("org.example.app:Documents/in.txt", str(out))
    assert out.read_text(encoding="utf-8") == "hello"
    for bad in ("org.example.app:../escape.txt", "org.example.app:", "noprefix/path", "bad bundle:x"):
        with pytest.raises(DeviceError):
            ext.push_file(str(source), bad)


def test_the_pasteboard_round_trips_without_an_app_switch(extension):
    ext, runner, _container, _recorders = extension
    ext.set_clipboard("copied")
    assert ext.get_clipboard() == "copied"
    assert [call[0] for call in runner.calls] == ["pbcopy", "pbpaste"]


def test_recording_starts_once_and_stops_with_sigint(extension, tmp_path):
    ext, _runner, _container, recorders = extension
    path = ext.start_recording()
    assert recorders[0].argv == ["xcrun", "simctl", "io", UDID, "recordVideo", "--force", path]
    with pytest.raises(DeviceError, match="already running"):
        ext.start_recording()
    saved = ext.stop_recording(str(tmp_path / "video.mp4"))
    assert open(saved, "rb").read() == b"mp4" and recorders[0].signals == [signal.SIGINT]
    with pytest.raises(DeviceError, match="no Simulator recording"):
        ext.stop_recording(str(tmp_path / "again.mp4"))


def test_a_failing_simctl_call_raises_a_device_error(extension):
    ext, runner, _container, _recorders = extension
    runner.__class__ = type("Failing", (Simctl,), {"__call__": lambda self, argv, **o: SimpleNamespace(
        returncode=1, stdout="")})
    with pytest.raises(DeviceError, match="exit code 1"):
        ext.get_clipboard()


def test_booted_simulators_are_listed_from_simctl_json():
    payload = {"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-18-0": [
        {"udid": UDID, "name": "iPhone 16", "state": "Booted"},
        {"udid": "not-a-udid", "name": "x", "state": "Booted"}]}}

    def runner(argv, **_options):
        assert argv == ["xcrun", "simctl", "list", "devices", "booted", "-j"]
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload))
    assert list_ios_simulators(runner=runner) == [
        {"udid": UDID, "name": "iPhone 16", "runtime": "com.apple.CoreSimulator.SimRuntime.iOS-18-0"}]


def test_using_a_simulator_registers_and_removes_the_ios_adapter(monkeypatch):
    from je_auto_control.wrapper import mobile_extensions
    monkeypatch.setattr(mobile_extensions, "_FACTORIES", {})
    report = use_ios_simulator(UDID.lower())
    assert report["registered"] is True and report["udid"] == UDID
    assert mobile_extensions._FACTORIES["ios"](object()).name == "simctl"
    assert use_ios_simulator(None) == {"registered": False} and "ios" not in mobile_extensions._FACTORIES
    assert use_ios_simulator("") == {"registered": False}
    with pytest.raises(DeviceError):
        use_ios_simulator("not-a-udid")


def test_the_commands_reach_the_executor_and_rbac():
    from je_auto_control.utils.executor.action_executor import executor
    from je_auto_control.utils.rbac.policy import COMMAND_CAPABILITIES, Capability
    assert {"AC_ios_use_simulator", "AC_ios_list_simulators"} <= set(executor.known_commands())
    assert COMMAND_CAPABILITIES["AC_ios_use_simulator"] == Capability.DRIVE_INPUT
    assert simctl.__all__ == ["SimctlExtension", "list_ios_simulators", "use_ios_simulator"]


def test_a_recording_is_stopped_through_a_different_extension_than_started_it(tmp_path, monkeypatch):
    from je_auto_control.wrapper import mobile_extensions
    monkeypatch.setattr(mobile_extensions, "_FACTORIES", {})
    monkeypatch.setattr(simctl, "_simctl_available", lambda: True)
    monkeypatch.setattr(SimctlExtension.__init__, "__kwdefaults__", {
        "runner": None, "popen": Recorder, "available": lambda: True})
    use_ios_simulator(UDID)
    factory = mobile_extensions._FACTORIES["ios"]
    started, stopped = factory(object()), factory(object())
    assert started is not stopped  # what two AC_ios_* commands get
    started.start_recording()
    assert open(stopped.stop_recording(str(tmp_path / "new" / "video.mp4")), "rb").read() == b"mp4"


def test_a_time_limit_never_ends_a_later_recording(extension, tmp_path, recordings):
    ext, _runner, _container, recorders = extension
    ext.start_recording(time_limit_s=3600)
    first = recordings[UDID].timer
    ext.stop_recording(str(tmp_path / "one.mp4"))
    assert first.finished.is_set()  # cancelled
    ext.start_recording()
    first.function(*first.args)  # even one that had already fired holds only its own process
    assert recorders[1].signals == []
    with pytest.raises(DeviceError, match="time_limit_s"):
        SimctlExtension(UDID.replace("0123ABCD", "FFFFFFFF"), available=lambda: True).start_recording(time_limit_s=-1)
    ext.stop_recording(str(tmp_path / "two.mp4"))


def test_a_recording_that_wrote_nothing_is_a_device_error(extension, tmp_path):
    ext, _runner, _container, _recorders = extension
    os.unlink(ext.start_recording())
    with pytest.raises(DeviceError, match="produced no file"):
        ext.stop_recording(str(tmp_path / "video.mp4"))


@pytest.mark.parametrize("failure, expected", [
    (subprocess.TimeoutExpired(["xcrun", "SECRET"], 120), DeviceTimeoutError), (FileNotFoundError("xcrun"), DeviceError)])
def test_simctl_failures_stay_in_the_framework_family(failure, expected):
    def runner(_argv, **_options):
        raise failure
    ext = SimctlExtension(UDID, runner=runner, available=lambda: True)
    for call in (ext.get_clipboard, lambda: list_ios_simulators(runner=runner)):
        with pytest.raises(expected) as caught:
            call()
        assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize("stdout", ["not json", "[]"])
def test_an_unreadable_simulator_list_is_a_device_error(stdout):
    with pytest.raises(DeviceError, match="no device list"):
        list_ios_simulators(runner=lambda _argv, **_options: SimpleNamespace(returncode=0, stdout=stdout))


def test_a_blank_container_never_becomes_the_working_directory(tmp_path):
    source = tmp_path / "in.txt"
    source.write_text("x", encoding="utf-8")
    ext = SimctlExtension(UDID, available=lambda: True,
                          runner=lambda _argv, **_options: SimpleNamespace(returncode=0, stdout="\n"))
    with pytest.raises(DeviceError, match="no data container"):
        ext.push_file(str(source), "org.example.app:Documents/in.txt")


def test_clipboard_text_keeps_its_carriage_returns():
    board = {}

    def runner(argv, **options):
        assert "text" not in options  # text mode would turn CRLF into LF
        if argv[2] == "pbcopy":
            board["value"] = options["input"]
        return SimpleNamespace(returncode=0, stdout=board.get("value", b"") if argv[2] == "pbpaste" else b"")
    simulator = SimctlExtension(UDID, runner=runner, available=lambda: True)
    simulator.set_clipboard("a\r\nb李")
    assert simulator.get_clipboard() == "a\r\nb李"
