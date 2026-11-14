"""Cancellable EI domain RPC over the existing owned helper channel."""
from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable, Sequence

from je_auto_control.linux_wayland._input_state import InputFailure
from je_auto_control.linux_wayland.ei_protocol import (
    EiProtocolError, InputAck, InputEvent, batch_wire, encode, timeout_value,
)
from je_auto_control.utils.agent_runtime.owned_channel_factory import HelperChannel
from je_auto_control.utils.exception.cancellation import cancellation_checkpoint
from je_auto_control.utils.exception.control_signals import raise_caused_run_interruption
from je_auto_control.utils.exception.exceptions import AutoControlException


def _channel() -> HelperChannel:
    from je_auto_control.utils.agent_runtime.owned_channel_factory import owned_channel
    return owned_channel([sys.executable, "-u", "-m", "je_auto_control.linux_wayland.ei_worker"], display=True)


def _refuse(status: InputFailure) -> None:
    from je_auto_control.linux_wayland.libei import LibeiUnavailable
    error = LibeiUnavailable(status.message, state=status.state, fallback_allowed=status.fallback_allowed)
    error.status = status
    raise error


class EiWorkerClient:
    """Own one EI helper; failed or uncertain operations never reconnect or replay."""

    def __init__(self, *, factory: Callable[[], HelperChannel] = _channel) -> None:
        self._factory = factory
        self._channel: HelperChannel | None = None
        self._starting = False
        self._request_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._closed = threading.Event()
        self._sequence = 0
        self._available: bool | None = None
        self._connected = False
        self._state = "unverified"
        self._failure: InputFailure | None = None
        self.cleanup_confirmed = False

    @property
    def retired(self) -> bool:
        """Report owned-channel retirement only; this is not native input-release evidence."""
        channel = self._channel
        return self._closed.is_set() and not self._starting and (channel is None or channel.retired)

    @property
    def is_available(self) -> bool:
        """Probe loadability in the helper, without requesting portal consent."""
        if self._available is None:
            self._request("probe", {}, 5.0)
        return bool(self._available)

    @property
    def is_connected(self) -> bool:
        """Read cached connection state without performing IPC."""
        return self._connected and not self._closed.is_set() and self._failure is None

    def observed_state(self) -> str:
        """Return passive cached metadata without probing, consent or a lock wait."""
        return self._failure.state if self._failure is not None else self._state

    def _acquire(self, deadline: float) -> None:
        while True:
            cancellation_checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EiProtocolError("EI request queue deadline exhausted")
            if self._request_lock.acquire(timeout=min(remaining, 0.05)):
                return

    def _owned(self) -> HelperChannel:
        with self._lifecycle_lock:
            if self._closed.is_set():
                raise EiProtocolError("EI helper has closed")
            if self._channel is not None:
                return self._channel
            self._starting = True
        try:
            channel = self._factory()
            with self._lifecycle_lock:
                self._channel = channel
        finally:
            self._starting = False
        if self._closed.is_set():
            channel.close()
            raise EiProtocolError("EI helper closed during startup")
        return channel

    def _remember_state(self, value: dict[str, Any]) -> None:
        if (type(value.get("available")) is not bool or type(value.get("connected")) is not bool
                or value.get("state") not in {"available", "unverified", "paused", "revoked"}):
            raise EiProtocolError("invalid EI state reply")
        self._available, self._connected, self._state = value["available"], value["connected"], value["state"]

    def _reply(self, reply: Any, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        encode(reply)
        if (not isinstance(reply, dict) or type(reply.get("version")) is not int or reply["version"] != 1
                or type(reply.get("sequence")) is not int or reply["sequence"] != self._sequence
                or type(reply.get("ok")) is not bool):
            raise EiProtocolError("invalid EI reply")
        if not reply["ok"]:
            self._failure_reply(reply)
        if set(reply) != {"version", "sequence", "ok", "value"} or not isinstance(reply["value"], dict):
            raise EiProtocolError("invalid EI success reply")
        value = reply["value"]
        return self._value(value, operation, arguments)

    def _value(self, value: dict[str, Any], operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if operation == "disconnect":
            if set(value) != {"cleaned"} or type(value["cleaned"]) is not bool:
                raise EiProtocolError("invalid EI cleanup reply")
        else:
            fields = {"available", "connected", "state"} | ({"emitted"} if operation == "send" else set())
            if set(value) != fields:
                raise EiProtocolError("invalid EI state fields")
            if operation == "send":
                if type(value["emitted"]) is not int or value["emitted"] != len(arguments["events"]):
                    raise EiProtocolError("incomplete EI acknowledgement")
            self._remember_state(value)
        return value

    def _failure_reply(self, reply: dict[str, Any]) -> None:
        if set(reply) != {"version", "sequence", "ok", "failure"}:
            raise EiProtocolError("invalid EI failure reply")
        failure = reply["failure"]
        if not isinstance(failure, dict) or set(failure) != {"state", "backend", "fallback_allowed"}:
            raise EiProtocolError("invalid EI failure fields")
        self._failure = InputFailure(message="EI helper refused the operation", **failure)
        _refuse(self._failure)

    def _exchange(self, operation: str, arguments: dict[str, Any], deadline: float,
                  check: Callable[[], None] = cancellation_checkpoint) -> dict[str, Any]:
        channel = self._owned()
        self._sequence += 1
        payload = {"version": 1, "sequence": self._sequence, "arguments": arguments}
        encode({"id": "0" * 32, "operation": operation, "payload": payload})
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EiProtocolError("EI request deadline exhausted")
        reply = channel.request(operation, payload, timeout=remaining, check=check)
        check()
        if self._closed.is_set():
            raise EiProtocolError("EI reply arrived after close")
        return self._reply(reply, operation, arguments)

    def _retire_failed(self, error: BaseException) -> None:
        if self._failure is None:
            self._failure = InputFailure("failed", "libei", "EI helper outcome is uncertain", fallback_allowed=False)
        self._closed.set()
        channel = self._channel
        if channel is not None:
            try:
                channel.close()
            except (AutoControlException, OSError, RuntimeError, ValueError):
                pass
        raise_caused_run_interruption(error)
        if not isinstance(error, Exception):
            raise error
        _refuse(self._failure)

    def _request(self, operation: str, arguments: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_value(timeout_s)
        if self._failure is not None:
            _refuse(self._failure)
        self._acquire(deadline)
        try:
            try:
                return self._exchange(operation, arguments, deadline)
            except BaseException as error:  # reason: cancellation must retire this owned helper before propagating
                self._retire_failed(error)
                raise
        finally:
            self._request_lock.release()

    def connect(self, *, timeout: float = 3.0, socket_path: bytes | None = None) -> None:
        """Connect this existing worker once; no parent process loads native EI."""
        timeout_value(timeout)
        if socket_path is not None and (not isinstance(socket_path, bytes) or len(socket_path) > 1024
                                        or b"\0" in socket_path):
            raise EiProtocolError("invalid EI socket path")
        if not self.is_connected:
            self._request("connect", {"timeout": timeout, "socket_path": None if socket_path is None
                                     else socket_path.hex()}, timeout)

    def send(self, events: Sequence[InputEvent], *, timeout_s: float = 5.0) -> InputAck:
        """Emit one bounded batch with no retry after any uncertain result."""
        batch = batch_wire(events)
        result = self._request("send", {"events": batch}, timeout_s)
        return InputAck(result["emitted"])

    def press_key(self, keycode: int) -> None:
        """Emit a key press through the owned helper."""
        self.send((InputEvent("press_key", (keycode,)),))

    def release_key(self, keycode: int) -> None:
        """Emit a key release through the owned helper."""
        self.send((InputEvent("release_key", (keycode,)),))

    def press_button(self, button_code: int) -> None:
        """Emit a button press through the owned helper."""
        self.send((InputEvent("press_button", (button_code,)),))

    def release_button(self, button_code: int) -> None:
        """Emit a button release through the owned helper."""
        self.send((InputEvent("release_button", (button_code,)),))

    def click_button(self, button_code: int) -> None:
        """Emit press/release together as a validated batch."""
        self.send((InputEvent("press_button", (button_code,)), InputEvent("release_button", (button_code,))))

    def set_position(self, x: int, y: int) -> None:
        """Emit an absolute position through the owned helper."""
        self.send((InputEvent("set_position", (x, y)),))

    def scroll(self, dx: int, dy: int) -> None:
        """Emit discrete wheel detents through the owned helper."""
        self.send((InputEvent("scroll", (dx, dy)),))

    def disconnect(self) -> None:
        """Attempt graceful release when idle, then retire without waiting for a pending RPC."""
        channel = self._channel
        if channel is None:
            with self._lifecycle_lock:
                self._closed.set()
                channel = self._channel
            if channel is None:
                if self._starting:
                    raise EiProtocolError("EI helper startup retirement is unconfirmed")
                return
        acquired = self._request_lock.acquire(blocking=False)
        try:
            if acquired and not self._closed.is_set():
                try:
                    result = self._exchange("disconnect", {}, time.monotonic() + 1.0, lambda: None)
                    self.cleanup_confirmed = result["cleaned"]
                except (AutoControlException, OSError, RuntimeError, ValueError):
                    self.cleanup_confirmed = False
            self._closed.set()
            self._connected = False
            channel.close()
            if not channel.retired:
                raise EiProtocolError("EI helper retirement is unconfirmed")
        finally:
            if acquired:
                self._request_lock.release()

    close = disconnect
