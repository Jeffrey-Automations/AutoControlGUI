"""Fixed owned-helper entry point; only this process loads and drives native EI."""
from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO, Callable

from je_auto_control.linux_wayland.ei_protocol import (
    EiProtocolError, InputBackend, InputEvent, MAX_PACKET, encode, events_from_wire, timeout_value, unique_object,
)
from je_auto_control.linux_wayland._input_state import InputFailure
from je_auto_control.utils.exception.exceptions import AutoControlException


def _native_backend() -> InputBackend:
    from je_auto_control.linux_wayland.libei import LibeiBackend
    return LibeiBackend()


class EiWorker:
    """Own one native backend and its pressed-input ledger until process retirement."""

    def __init__(self, factory: Callable[[], InputBackend] = _native_backend) -> None:
        self._factory = factory
        self._backend: InputBackend | None = None
        self._sequence = 0
        self._failed = False
        self._pressed: set[tuple[str, int]] = set()

    def _get_backend(self) -> InputBackend:
        if self._backend is None:
            self._backend = self._factory()
        return self._backend

    def _state(self) -> dict[str, Any]:
        backend = self._get_backend()
        return {"available": backend.is_available, "connected": backend.is_connected,
                "state": backend.observed_state()}

    def _emit(self, event: InputEvent) -> None:
        backend = self._get_backend()
        group = "key" if event.kind.endswith("key") else "button"
        if event.kind.startswith("press_"):
            self._pressed.add((group, event.arguments[0]))
        getattr(backend, event.kind)(*event.arguments)
        if event.kind.startswith("release_"):
            self._pressed.discard((group, event.arguments[0]))

    def close(self) -> bool:
        """Attempt every owned release and teardown; report only local cleanup success."""
        backend = self._backend
        if backend is None:
            return True
        cleaned = True
        for kind, code in tuple(self._pressed):
            try:
                getattr(backend, "release_" + kind)(code)
                self._pressed.discard((kind, code))
            except (AutoControlException, OSError, RuntimeError, ValueError):
                cleaned = False
        try:
            backend.disconnect()
        except (AutoControlException, OSError, RuntimeError, ValueError):
            cleaned = False
        return cleaned

    def _execute(self, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if operation in {"probe", "state", "disconnect"}:
            if arguments:
                raise EiProtocolError("unexpected EI arguments")
            if operation == "disconnect":
                return {"cleaned": self.close()}
            return self._state()
        if operation == "connect":
            self._connect(arguments)
            return self._state()
        if operation != "send" or set(arguments) != {"events"}:
            raise EiProtocolError("unknown EI operation")
        events = events_from_wire(arguments["events"])
        for event in events:
            self._emit(event)
        return {"emitted": len(events), **self._state()}

    def _connect(self, arguments: dict[str, Any]) -> None:
        if set(arguments) != {"timeout", "socket_path"}:
            raise EiProtocolError("invalid EI connect fields")
        timeout = timeout_value(arguments["timeout"])
        path = arguments["socket_path"]
        if path is not None and (not isinstance(path, str) or len(path) > 2048 or "\0" in path):
            raise EiProtocolError("invalid EI socket path")
        socket_path = None if path is None else bytes.fromhex(path)
        if socket_path is not None and (not socket_path or b"\0" in socket_path):
            raise EiProtocolError("invalid EI socket path")
        self._get_backend().connect(timeout=timeout, socket_path=socket_path)

    def _envelope(self, message: Any) -> tuple[str, str, dict[str, Any]]:
        """Validate correlation and sequence before touching native state."""
        if not isinstance(message, dict) or set(message) != {"id", "operation", "payload"}:
            raise EiProtocolError("invalid EI envelope")
        request_id, operation, payload = message["id"], message["operation"], message["payload"]
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise EiProtocolError("invalid EI request ID")
        self._payload(payload, operation)
        return request_id, operation, payload["arguments"]

    def _payload(self, payload: Any, operation: Any) -> None:
        if (not isinstance(payload, dict) or set(payload) != {"version", "sequence", "arguments"}
                or type(payload["version"]) is not int or payload["version"] != 1
                or type(payload["sequence"]) is not int or payload["sequence"] != self._sequence + 1
                or not isinstance(payload["arguments"], dict) or not isinstance(operation, str)):
            raise EiProtocolError("invalid EI request sequence")

    def handle(self, message: Any) -> tuple[dict[str, Any], bool]:
        """Preserve expected authority failures as protocol data."""
        request_id, operation, arguments = self._envelope(message)
        self._sequence += 1
        result: dict[str, Any] = {"version": 1, "sequence": self._sequence}
        try:
            if self._failed and operation != "disconnect":
                raise EiProtocolError("EI session has failed")
            value = self._execute(operation, arguments)
            result.update(ok=True, value=value)
        except (AutoControlException, OSError, RuntimeError, ValueError, AttributeError) as error:
            self._failed = True
            status = getattr(error, "status", None)
            if not isinstance(status, InputFailure) or operation == "send":
                status = InputFailure("failed", "libei", "EI helper operation failed", fallback_allowed=False)
            result.update(ok=False, failure={"state": status.state, "backend": status.backend,
                                            "fallback_allowed": status.fallback_allowed})
        return {"id": request_id, "result": result}, operation == "disconnect"

    def run(self, source: BinaryIO, sink: BinaryIO) -> None:
        """Read bounded inherited-pipe frames; EOF and malformed input retire this worker."""
        try:
            while line := source.readline(MAX_PACKET + 1):
                if len(line) > MAX_PACKET or not line.endswith(b"\n"):
                    return
                try:
                    message = json.loads(line, object_pairs_hook=unique_object)
                    reply, stop = self.handle(message)
                except (ValueError, RecursionError):
                    return
                sink.write(encode(reply))
                sink.flush()
                if stop:
                    return
        finally:
            self.close()


def main() -> None:
    """Launch the fixed worker with parent-death retirement, never a caller-selected factory."""
    if len(sys.argv) != 1:
        raise SystemExit(2)
    from je_auto_control.utils.agent_runtime.parent_watch import start_parent_watch
    start_parent_watch()
    EiWorker().run(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main()
