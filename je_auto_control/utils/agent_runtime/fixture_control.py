"""Owned fixture RPC transport with bounded requests and retained process retirement."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import threading
from typing import Any, Callable, Mapping

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.native_channel import OwnedChannel
from je_auto_control.utils.agent_runtime.wire_data import detached, positive
from je_auto_control.utils.process_memory.fixture_probe import FixtureBinding


def _state_reply(value: dict[str, Any]) -> None:
    document, status = value.get("document_id"), value.get("job_status")
    sequence = value.get("sequence")
    if (not isinstance(document, int) or isinstance(document, bool) or not 0 <= document < 2**32
            or not isinstance(status, str) or status not in {"ready", "busy", "done"}):
        raise AgentTaskError("invalid fixture state reply")
    if (not isinstance(sequence, int) or isinstance(sequence, bool)
            or not 0 <= sequence < 2**64 or sequence % 2):
        raise AgentTaskError("invalid fixture revision reply")


def _validate_reply(value: Any, command: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentTaskError("invalid fixture control reply")
    if set(value) == {"kind", "code"} and value["kind"] == "error":
        if value["code"] in ("invalid_request", "invalid_state", "sequence_exhausted",
                             "target_changed",
                             "state_changed", "operation_conflict", "operation_limit"):
            return value
        raise AgentTaskError("invalid fixture refusal")
    keys = {"kind", "document_id", "job_status", "sequence"}
    if command == "compare_set":
        keys |= {"operation_id", "launch_nonce", "comparison"}
    kind = "receipt" if command == "compare_set" else "snapshot"
    if set(value) != keys or value["kind"] != kind:
        raise AgentTaskError("invalid fixture control reply")
    _state_reply(value)
    if command == "compare_set":
        _receipt_identity(value)
    return value


def _receipt_identity(value: dict[str, Any]) -> None:
    operation, nonce = value["operation_id"], value["launch_nonce"]
    if (not isinstance(operation, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", operation) is None
            or not isinstance(nonce, str) or re.fullmatch(r"[0-9a-f]{32}", nonce) is None
            or value["comparison"] != "atomic"):
        raise AgentTaskError("invalid fixture receipt identity")


@dataclass(frozen=True)
class FixtureSession:
    """Private validated launch locations and nonce, not an attested process identity."""

    binding: FixtureBinding = field(repr=False)
    launch_nonce: str = field(repr=False)


class OwnedFixtureControl:
    """Reuse the host-owned channel; no task can supply argv or choose another process."""

    def __init__(self, channel: OwnedChannel, challenge: bytes) -> None:
        """Take channel ownership only after validating the host's challenge."""
        if not isinstance(challenge, bytes) or len(challenge) != 16 or not any(challenge):
            raise AgentTaskError("fixture control requires a nonzero launch challenge")
        self._channel, self._challenge = channel, challenge
        self._session: FixtureSession | None = None
        self._terminal = threading.Event()
        self._lock = threading.Lock()

    def _live(self, checkpoint: Callable[[], None]) -> None:
        if self._terminal.is_set() or self._channel.retired:
            raise AgentTaskError("fixture control is retired")
        checkpoint()
        if self._terminal.is_set() or self._channel.retired:
            raise AgentTaskError("fixture control is retired")

    def bootstrap(self, *, timeout: float, checkpoint: Callable[[], None]) -> FixtureSession:
        """Validate bootstrap once; the parent must still attest the measured native identity."""
        positive(timeout, "fixture deadline", 1)
        with self._lock:
            self._live(checkpoint)
            if self._session is not None:
                return self._session
            try:
                value = self._channel.request("bootstrap", {}, timeout=timeout, check=checkpoint)
                if not isinstance(value, dict):
                    raise AgentTaskError("invalid fixture bootstrap")
                binding = FixtureBinding.from_bootstrap(self._challenge, value)
                nonce = value.get("launch_nonce")
                if not isinstance(nonce, str) or re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
                    raise AgentTaskError("invalid fixture launch nonce")
                self._live(checkpoint)
                self._session = FixtureSession(binding, nonce)
                return self._session
            except BaseException as error:
                self._retire_failed(error)
                raise

    def request(self, payload: Mapping[str, Any], *, timeout: float,
                checkpoint: Callable[[], None]) -> Mapping[str, Any]:
        """Send one bounded control request; a failed exchange permanently retires use."""
        positive(timeout, "fixture deadline", 1)
        with self._lock:
            self._live(checkpoint)
            if self._session is None:
                raise AgentTaskError("fixture control requires validated bootstrap")
            value = detached(payload)
            if (not isinstance(value, dict)
                    or value.get("command") not in ("snapshot", "compare_set")):
                raise AgentTaskError("unsupported fixture control command")
            envelope = {"id": "0" * 32, "operation": "control", "payload": value}
            if len(json.dumps(envelope, ensure_ascii=False).encode("utf-8")) + 1 > 1024:
                raise AgentTaskError("fixture control request exceeds its frame limit")
            try:
                reply = self._channel.request("control", value, timeout=timeout, check=checkpoint)
                reply = _validate_reply(reply, value["command"])
                self._live(checkpoint)
                return reply
            except BaseException as error:
                self._retire_failed(error)
                raise

    def _retire_failed(self, error: BaseException) -> None:
        self._terminal.set()
        try:
            self._channel.close()
        except BaseException as cleanup:
            raise error from cleanup

    def close(self) -> None:
        """Stop further use and prove owned process retirement; retain the owner on failure."""
        self._terminal.set()
        self._channel.close()
        if not self._channel.retired:
            raise AgentTaskError("fixture process retirement is unconfirmed")
