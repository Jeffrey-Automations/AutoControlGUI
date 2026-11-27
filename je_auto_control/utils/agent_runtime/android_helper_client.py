"""Speak protocol version 1 to the device-side helper; every reply has a closed schema or is refused.

The helper (``native/android_helper``) is the only component that can fence old writers on the
device, so this client never interprets a missing, malformed or unexpected reply as success.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable, Literal

from je_auto_control.utils.agent_runtime.errors import AgentTaskError

HELPER_SOCKET = "je_auto_control_helper"
_TOKEN = re.compile(r"[0-9a-f]{32}")
_BOOT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_STATUSES = ("queued", "injecting", "completed", "rejected", "fenced", "failed")
# android.view.KeyEvent codes of the symbolic keys AC_android_key accepts.
KEYCODES = {"BACK": 4, "ENTER": 66, "TAB": 61, "DEL": 67, "DPAD_UP": 19, "DPAD_DOWN": 20,
            "DPAD_LEFT": 21, "DPAD_RIGHT": 22, "MOVE_HOME": 122, "MOVE_END": 123}
Status = Literal["queued", "injecting", "completed", "rejected", "fenced", "failed"]


def _token(value: Any, name: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise AgentTaskError(f"Android helper {name} is invalid")
    return value


def _flag(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise AgentTaskError(f"Android helper {name} is invalid")
    return value


@dataclass(frozen=True)
class HelperHello:
    """The helper's boot and instrumentation identity and its current epoch."""

    boot_id: str
    helper_epoch: str
    epoch: str


@dataclass(frozen=True)
class HelperFence:
    """The device's account of one fence: what it stopped and whether any write remains."""

    epoch: str
    fenced: tuple[str, ...]
    inflight: str | None
    queue_empty: bool


@dataclass(frozen=True)
class HelperSettlement:
    """The device's account of one command; only ``completed`` with released input certifies an effect."""

    request_id: str
    boot_id: str
    epoch: str
    status: Status
    input_released: bool
    queue_empty: bool


def helper_command(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Map a reviewed tool call to the helper's closed command shape; text input has no helper command."""
    if name == "AC_android_tap":
        return {"kind": "tap", "x": arguments["x"], "y": arguments["y"]}
    if name == "AC_android_swipe":
        return {"kind": "swipe", "x": arguments["x1"], "y": arguments["y1"], "to_x": arguments["x2"],
                "to_y": arguments["y2"], "duration_ms": arguments.get("duration_ms", 250)}
    if name == "AC_android_key":
        key = str(arguments["key"]).removeprefix("KEYCODE_")
        if key not in KEYCODES:
            raise AgentTaskError("Android key is outside the finite app-input set")
        return {"kind": "key", "keycode": KEYCODES[key]}
    raise AgentTaskError("Android helper has no command for this tool; text input stays unsupported here")


class AndroidHelperClient:
    """One request per fresh ADB local-socket connection to the helper on one selected transport."""

    def __init__(self, server: Any, transport: Callable[[float, Callable[[], None]], int]) -> None:
        self._server, self._transport = server, transport

    def _call(self, request: dict[str, Any], keys: set[str], *, timeout: float,
              check: Callable[[], None]) -> dict[str, Any]:
        line = (json.dumps(request, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        raw = self._server.exchange_local(self._transport(timeout, check), HELPER_SOCKET, line,
                                          timeout=timeout, check=check)
        try:
            reply = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError):
            raise AgentTaskError("Android helper reply is not JSON") from None
        if not isinstance(reply, dict) or set(reply) != keys:
            raise AgentTaskError("Android helper reply has an unexpected schema")
        return reply

    def hello(self, *, timeout: float, check: Callable[[], None]) -> HelperHello:
        """Read the helper's boot and instrumentation identity."""
        reply = self._call({"op": "hello"}, {"protocol", "boot_id", "helper_epoch", "epoch"},
                           timeout=timeout, check=check)
        if reply["protocol"] != 1 or not isinstance(reply["boot_id"], str) or _BOOT.fullmatch(reply["boot_id"]) is None:
            raise AgentTaskError("Android helper protocol or boot identity is unsupported")
        return HelperHello(reply["boot_id"], _token(reply["helper_epoch"], "helper epoch"),
                           _token(reply["epoch"], "epoch"))

    def fence(self, epoch: str, *, timeout: float, check: Callable[[], None]) -> HelperFence:
        """Move the device to ``epoch`` for good; older queued commands are fenced, an injecting one stops."""
        reply = self._call({"op": "fence", "epoch": _token(epoch, "epoch")},
                           {"epoch", "fenced", "inflight", "queue_empty"}, timeout=timeout, check=check)
        fenced = reply["fenced"]
        if reply["epoch"] != epoch or not isinstance(fenced, list) or len(fenced) > 4096:
            raise AgentTaskError("Android helper fence reply does not match its request")
        inflight = reply["inflight"]
        return HelperFence(epoch, tuple(_token(item, "fenced id") for item in fenced),
                           None if inflight is None else _token(inflight, "inflight id"),
                           _flag(reply["queue_empty"], "queue state"))

    def begin(self, request_id: str, epoch: str, command: dict[str, Any], *, timeout: float,
              check: Callable[[], None]) -> tuple[bool, str]:
        """Queue one command under ``epoch``; a refusal means it was never queued."""
        reply = self._call({"op": "begin", "id": _token(request_id, "request id"), "epoch": _token(epoch, "epoch"),
                            "command": command}, {"id", "accepted", "reason"}, timeout=timeout, check=check)
        reason = reply["reason"]
        if reply["id"] != request_id or not (reason is None or isinstance(reason, str) and len(reason) <= 64):
            raise AgentTaskError("Android helper admission reply does not match its request")
        return _flag(reply["accepted"], "admission"), reason or ""

    def settle(self, request_id: str, *, timeout: float, check: Callable[[], None]) -> HelperSettlement:
        """Read the device's account of one command."""
        reply = self._call({"op": "settle", "id": _token(request_id, "request id")},
                           {"id", "boot_id", "epoch", "status", "input_released", "queue_empty"},
                           timeout=timeout, check=check)
        if reply["id"] != request_id or reply["status"] not in _STATUSES or not isinstance(reply["boot_id"], str):
            raise AgentTaskError("Android helper settlement does not match its request")
        return HelperSettlement(request_id, reply["boot_id"], _token(reply["epoch"], "epoch"), reply["status"],
                                _flag(reply["input_released"], "input release"),
                                _flag(reply["queue_empty"], "queue state"))
