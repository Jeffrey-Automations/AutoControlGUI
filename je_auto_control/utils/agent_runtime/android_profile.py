"""Host-reviewed Android target profiles: closed settings and the fixed helper-backed worker argv.

A profile names one ADB server port, one connection serial, the physical device and the one app
package it may drive; the task cannot widen any of them. Only the tools the device helper can run
are reviewed (tap, swipe, key): ``AC_android_text`` has no helper command. The worker runs with
this interpreter under ``-I`` and receives exactly these settings, never task options.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from je_auto_control.utils.agent_runtime.android_scope import validate_android_binding
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.models import detached

ANDROID_PROFILE_TOOLS = frozenset({"AC_android_tap", "AC_android_swipe", "AC_android_key"})
WORKER_MODULE = "je_auto_control.utils.agent_runtime.android_worker"
_REQUIRED = {"serial", "physical_id", "package"}
_OPTIONAL = {"adb_port": 5037, "user": 0, "idle_seconds": 60}


def _whole(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise AgentTaskError(f"Android profile {name} is out of range")
    return value


def android_settings(value: Any) -> dict[str, Any]:
    """Validate the closed Android settings and fill the defaults."""
    data = detached(value)
    if not isinstance(data, dict) or not _REQUIRED <= set(data) or set(data) - _REQUIRED - set(_OPTIONAL):
        raise AgentTaskError("Android profiles require serial, physical_id and package settings only")
    settings = {**_OPTIONAL, **data}
    serial = settings["serial"]
    if (not isinstance(serial, str) or not 1 <= len(serial) <= 256
            or any(ord(char) < 33 or ord(char) > 126 for char in serial)):
        raise AgentTaskError("Android profile serial must be an exact bounded token")
    _whole(settings["adb_port"], "ADB port", 1, 65535)
    _whole(settings["user"], "user", 0, 2**31 - 1)
    _whole(settings["idle_seconds"], "idle window", 1, 3600)
    validate_android_binding(settings["physical_id"], settings["package"], settings["user"])
    return settings


def check_android_apps(apps: tuple[str, ...], settings: dict[str, Any]) -> None:
    """The profile grants exactly the one package its settings bind."""
    if tuple(apps) != (settings["package"],):
        raise AgentTaskError("Android profiles grant exactly their configured app package")


def android_worker_argv(settings: dict[str, Any]) -> list[str]:
    """The fixed worker command for one reviewed profile."""
    return [sys.executable, "-I", "-m", WORKER_MODULE, json.dumps(android_settings(settings), sort_keys=True)]
