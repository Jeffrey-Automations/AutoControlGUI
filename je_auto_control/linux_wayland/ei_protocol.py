"""Bounded event batches and versioned replies for the owned EI helper."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Protocol, Sequence

from je_auto_control.utils.exception.exceptions import AutoControlException

MAX_PACKET = 16384
MAX_EVENTS = 128
_ARITY = {"press_key": 1, "release_key": 1, "press_button": 1, "release_button": 1,
          "set_position": 2, "scroll": 2}


class EiProtocolError(AutoControlException, ValueError):
    """The private EI wire contract was not satisfied."""


class InputBackend(Protocol):
    """Operations shared by the low-level backend and its owned-process proxy."""

    @property
    def is_available(self) -> bool: ...
    @property
    def is_connected(self) -> bool: ...
    def observed_state(self) -> str: ...
    def connect(self, *, timeout: float = 5.0, socket_path: bytes | None = None) -> None: ...
    def disconnect(self) -> None: ...
    def press_key(self, keycode: int) -> None: ...
    def release_key(self, keycode: int) -> None: ...
    def press_button(self, button_code: int) -> None: ...
    def release_button(self, button_code: int) -> None: ...
    def set_position(self, x: int, y: int) -> None: ...
    def scroll(self, dx: int, dy: int) -> None: ...


def timeout_value(value: Any) -> float:
    """Validate a finite positive deadline before queue admission."""
    if (type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 60):
        raise EiProtocolError("EI timeout must be finite and within 60 seconds")
    return float(value)


@dataclass(frozen=True)
class InputEvent:
    """One reviewed operation with bounded integer arguments."""

    kind: str
    arguments: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in _ARITY:
            raise EiProtocolError("unknown EI event")
        values = tuple(self.arguments)
        if len(values) != _ARITY[self.kind]:
            raise EiProtocolError("invalid EI event arity")
        ceiling = 65535 if len(values) == 1 else (1 << 24) - 1
        floor = 0 if len(values) == 1 else -ceiling
        if any(type(value) is not int or not floor <= value <= ceiling for value in values):
            raise EiProtocolError("invalid EI event argument")
        object.__setattr__(self, "arguments", values)

    def wire(self) -> dict[str, Any]:
        """Return a detached event object for the private transport."""
        return {"kind": self.kind, "arguments": list(self.arguments)}


@dataclass(frozen=True)
class InputAck:
    """Worker emission count, not a compositor application or input-release receipt."""

    emitted: int


def events_from_wire(value: Any) -> tuple[InputEvent, ...]:
    """Validate the entire batch before any backend emission."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_EVENTS:
        raise EiProtocolError("EI batch exceeds its bound")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"kind", "arguments"}:
            raise EiProtocolError("invalid EI event fields")
        if not isinstance(item["arguments"], list):
            raise EiProtocolError("invalid EI event arguments")
        result.append(InputEvent(item["kind"], tuple(item["arguments"])))
    return tuple(result)


def batch_wire(events: Sequence[InputEvent]) -> list[dict[str, Any]]:
    """Validate and serialize a bounded typed batch."""
    if not 1 <= len(events) <= MAX_EVENTS or any(not isinstance(event, InputEvent) for event in events):
        raise EiProtocolError("invalid EI batch")
    result = [event.wire() for event in events]
    events_from_wire(result)
    encode(result)
    return result


def encode(value: Any) -> bytes:
    """Encode one bounded JSON line; never truncate a protocol message."""
    packet = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode() + b"\n"
    if len(packet) > MAX_PACKET:
        raise EiProtocolError("EI packet exceeds its bound")
    return packet


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous duplicate fields in an incoming object."""
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise EiProtocolError("duplicate EI field")
        result[name] = value
    return result
