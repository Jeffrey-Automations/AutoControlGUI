"""Host-reviewed Android profiles: closed settings, one package, fixed worker argv. No device, no Qt."""
import json
import sys

import pytest

from je_auto_control.utils.agent_runtime import android_worker
from je_auto_control.utils.agent_runtime.android_profile import ANDROID_PROFILE_TOOLS, android_settings
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.target_config import AgentTargetProfile, reviewed_tools
from je_auto_control.utils.agent_runtime.target_factory import build_target

SETTINGS = {"serial": "emulator-5554", "physical_id": "reviewed-device", "package": "org.example.app"}


def profile(**changes):
    value = {"name": "phone", "kind": "android", "allowed_tools": ["AC_android_tap", "AC_android_key"],
             "apps": ["org.example.app"], "settings": dict(SETTINGS)}
    value.update(changes)
    return AgentTargetProfile.from_dict(value)


def test_a_profile_fills_defaults_and_reviews_only_helper_tools():
    built = profile()
    assert built.to_dict()["settings"] == {**SETTINGS, "adb_port": 5037, "user": 0, "idle_seconds": 60}
    assert reviewed_tools("android") == ANDROID_PROFILE_TOOLS
    assert "AC_android_text" not in ANDROID_PROFILE_TOOLS


@pytest.mark.parametrize("changes", [
    {"allowed_tools": ["AC_android_text"]}, {"allowed_tools": ["AC_android_shell"]},
    {"apps": ["org.other.app"]}, {"apps": ["org.example.app", "org.other.app"]}, {"apps": []},
    {"roots": ["C:/data"]},
    {"settings": {**SETTINGS, "adb_host": "10.0.0.2"}},
    {"settings": {**SETTINGS, "adb_port": 0}}, {"settings": {**SETTINGS, "idle_seconds": 0}},
    {"settings": {**SETTINGS, "serial": "has space"}},
    {"settings": {key: value for key, value in SETTINGS.items() if key != "physical_id"}},
])
def test_unreviewed_profiles_are_refused(changes):
    with pytest.raises(AgentTaskError):
        profile(**changes)


def test_the_factory_builds_a_remote_target_with_the_fixed_worker_argv():
    target = build_target(profile())
    argv = list(target._argv)
    assert argv[:4] == [sys.executable, "-I", "-m", "je_auto_control.utils.agent_runtime.android_worker"]
    assert json.loads(argv[4]) == android_settings(SETTINGS)
    assert target._device == {"platform": "android", "physical_id": "reviewed-device"}


def test_the_worker_wires_the_helper_provider_and_starts_the_physical_source(monkeypatch):
    started, made = [], {}

    class Source:
        def __init__(self, transport):
            made["transport"] = transport

        def set_handler(self, handler):
            made["handler"] = handler

        def start(self):
            started.append(True)

        def close(self):
            started.append("closed")

    monkeypatch.setattr(android_worker.AndroidDeviceSession, "transport", lambda self, timeout, check=None: 9)
    monkeypatch.setattr(android_worker, "getevent_source", lambda server, transport: Source(transport))
    adapter = android_worker.build_adapter({**SETTINGS, "idle_seconds": 30}, server=object())
    assert started == [True] and made["transport"] == 9
    provider = adapter._control
    assert type(provider).__name__ == "HelperControlProvider" and provider._idle == 30
    assert adapter.device == {"platform": "android", "physical_id": "reviewed-device"}


def test_a_failed_provider_closes_the_started_source(monkeypatch):
    closed = []

    class Source:
        def set_handler(self, handler):
            raise RuntimeError("cannot bind")

        def start(self):
            return None

        def close(self):
            closed.append(True)

    monkeypatch.setattr(android_worker.AndroidDeviceSession, "transport", lambda self, timeout, check=None: 9)
    monkeypatch.setattr(android_worker, "getevent_source", lambda server, transport: Source())
    with pytest.raises(RuntimeError):
        android_worker.build_adapter(SETTINGS, server=object())
    assert closed == [True]
