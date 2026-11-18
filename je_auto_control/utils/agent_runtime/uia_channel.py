"""Receive one correlated UI-fixture startup without writing commands or input acknowledgments."""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from .errors import AgentTaskError
from .native_channel import OwnedChannel
from .wire_data import positive


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise AgentTaskError("UI fixture packet contains duplicate keys")
    return result


class OwnedUiaChannel(OwnedChannel):
    """Retain the existing hidden process tree and deadlines for a receive-only protocol."""

    def __init__(self, argv: Sequence[str], *, cwd: str | None = None,
                 env: Mapping[str, str] | None = None) -> None:
        self._invalid = threading.Event()
        self._startup_taken = False
        super().__init__(argv, cwd=cwd, env=env)

    def _read(self) -> None:
        stream = self._process.stdout
        try:
            if stream is None:
                raise AgentTaskError("UI fixture has no startup pipe")
            line = stream.readline(1025)
            if not line.endswith(b"\n") or len(line) > 1024:
                raise AgentTaskError("UI fixture startup exceeds its bound")
            packet = json.loads(line, object_pairs_hook=_object)
            if not isinstance(packet, dict) or set(packet) != {"id", "result"}:
                raise AgentTaskError("UI fixture startup has an unknown envelope")
            self._emit(packet)
            stream.read(1)
            if not self._stop.is_set():
                raise AgentTaskError("UI fixture startup stream ended or repeated")
        except (OSError, ValueError):
            self._invalid.set()
            self._emit(AgentTaskError("UI fixture startup protocol failed"))

    def check_live(self) -> None:
        """Refuse a retired channel or any extra packet/EOF after its one startup frame."""
        self._fenced()
        if self._invalid.is_set():
            raise AgentTaskError("UI fixture startup channel is invalid")

    def bootstrap(self, challenge: bytes, *, timeout: float, check: Callable[[], None]) -> Any:
        """Wait once for the launch challenge; every failure retains retirement responsibility."""
        positive(timeout, "UI fixture deadline", 60)
        if type(challenge) is not bytes or len(challenge) != 16:
            raise AgentTaskError("UI fixture requires a 16-byte challenge")
        with self._request_lock:
            if self._startup_taken:
                raise AgentTaskError("UI fixture startup was already consumed")
            self._startup_taken = True
            try:
                self.check_live()
                result = self._receive(challenge.hex(), time.monotonic() + timeout, check, None, "startup")
                self.check_live()
                return result
            except BaseException as primary:  # reason: cancelled or failed startup must retire the owned process
                try:
                    self.close()
                except AgentTaskError as cleanup:
                    raise primary from cleanup
                raise

    def request(self, operation: str, payload: Any, *, timeout: float,
                check: Callable[[], None] = lambda: None,
                on_event: Callable[[dict[str, Any]], None] | None = None) -> Any:
        """The UI fixture grants no command or input channel."""
        raise AgentTaskError("UI fixture channel is receive-only")
