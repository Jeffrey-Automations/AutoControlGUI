"""Ground one owned fixture command in reviewed memory evidence and strict IPC receipts."""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Protocol

from je_auto_control.utils.agent_runtime.context import current_operation
from je_auto_control.utils.agent_runtime.errors import (
    AgentEffectUnknown, AgentObservationStale, AgentTaskError,
)
from je_auto_control.utils.agent_runtime.memory_target import MemoryBinding
from je_auto_control.utils.agent_runtime.models import AgentTaskSpec
from je_auto_control.utils.agent_runtime.policy import TaskPolicy
from je_auto_control.utils.agent_runtime.semantic_target import (
    SemanticReceipt, SemanticSnapshot, _identifier,
)
from je_auto_control.utils.exception.control_signals import raise_if_run_interrupted
from je_auto_control.utils.executor.run_control import ExecutionStopped

FIXTURE_COMMAND = "AC_fixture_set_state"
_REFUSALS = frozenset({"invalid_request", "invalid_state", "sequence_exhausted",
                       "operation_conflict", "operation_limit"})


class FixtureControl(Protocol):
    """Owned bounded transport; private launch data never comes from task arguments."""

    def request(self, payload: Mapping[str, Any], *, timeout: float,
                checkpoint: Callable[[], None]) -> Mapping[str, Any]:
        """Exchange one bounded command; retire the stream after timeout or protocol failure."""

    def close(self) -> None:
        """Prove owned transport retirement or raise while retaining ownership."""


def _arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, Mapping) or set(arguments) != {"document_id", "job_status"}:
        raise AgentTaskError("fixture command requires document_id and job_status")
    document, status = arguments["document_id"], arguments["job_status"]
    if not isinstance(document, int) or isinstance(document, bool) or not 0 <= document < 2**32:
        raise AgentTaskError("fixture document ID is invalid")
    if not isinstance(status, str) or status not in {"ready", "busy", "done"}:
        raise AgentTaskError("fixture job status is invalid")
    return {"document_id": document, "job_status": status}


def _check_refusal(reply: Mapping[str, Any]) -> None:
    if set(reply) == {"kind", "code"} and reply["kind"] == "error":
        code = reply["code"]
        if code in ("state_changed", "target_changed"):
            raise AgentObservationStale("fixture changed before commit")
        if isinstance(code, str) and code in _REFUSALS:
            raise AgentTaskError("fixture command was refused")


class FixtureCommands:
    """Use only compare_set; never retry unknown effects or infer trust from a nonce."""

    def __init__(self, binding: MemoryBinding, launch_nonce: str, control: FixtureControl) -> None:
        if (not isinstance(launch_nonce, str) or re.fullmatch(r"[0-9a-f]{32}", launch_nonce) is None
                or set(binding.fields) != {"document_id", "job_status"}
                or binding.probe.probe_id != "fixture-document"
                or binding.probe.schema_version != "1"):
            raise AgentTaskError("fixture commands require the reviewed schema-one binding")
        self._binding, self._nonce, self._control = binding, launch_nonce, control
        self._terminal = False

    def ready(self, spec: AgentTaskSpec) -> tuple[bool, str]:
        """Require the exact target and the fixture's one reviewed operation."""
        if self._terminal:
            raise AgentTaskError("fixture command owner is retired")
        if spec.target != self._binding.target_id or set(spec.allowed_tools) != {FIXTURE_COMMAND}:
            raise AgentTaskError("fixture task exceeds the reviewed command scope")
        return True, ""

    def _expected(self, value: SemanticSnapshot) -> None:
        binding = self._binding
        if (value.target_id != binding.target_id or value.identity_digest != binding.identity.digest
                or value.adapter_id != binding.probe.probe_id or value.schema_version != "1"
                or value.source != "process_memory"):
            raise AgentObservationStale("fixture observation belongs to another target")
        if value.revision is None or set(dict(value.fields)) != set(binding.fields):
            raise AgentObservationStale("fixture command requires a complete checked revision")
        if value.revision >= 2**64 - 2:
            raise AgentTaskError("fixture sequence is exhausted")

    def perform_grounded(self, name: str, arguments: Mapping[str, Any], *,
                         expected: SemanticSnapshot, operation_id: str) -> SemanticReceipt:
        """Bind dispatch and confirmation to the original revision and journal operation ID."""
        operation = current_operation()
        if self._terminal or operation is None:
            raise AgentTaskError("fixture command requires a live managed scope")
        self.ready(operation.spec)
        TaskPolicy(operation.spec).check(name, arguments)
        if name != FIXTURE_COMMAND:
            raise AgentTaskError("unsupported fixture command")
        values = _arguments(arguments)
        _identifier(operation_id)
        self._expected(expected)
        payload = {"command": "compare_set", "operation_id": operation_id,
                   "launch_nonce": self._nonce,
                   "expected_sequence": expected.revision, **values}
        operation.checkpoint()
        reply = self._exchange(payload, operation.checkpoint)
        try:
            return self._receipt(reply, payload)
        except AgentEffectUnknown:
            self._terminal = True
            raise

    def _exchange(self, payload: Mapping[str, Any],
                  checkpoint: Callable[[], None]) -> Mapping[str, Any]:
        interruption: BaseException | None = None

        def checked() -> None:
            nonlocal interruption
            try:
                checkpoint()
            except BaseException as error:
                interruption = error
                raise

        try:
            reply = self._control.request(payload, timeout=1.0, checkpoint=checked)
            if interruption is not None:
                raise interruption
            checked()
            return reply
        except BaseException as error:  # reason: retire, preserving signals and sanitizing details
            self._terminal = True
            if interruption is not None:
                raise interruption from None
            if not isinstance(error, Exception) or isinstance(error, ExecutionStopped):
                raise
            raise_if_run_interrupted(error)
            raise AgentEffectUnknown("fixture reply unavailable; readback required") from None

    def _receipt(self, reply: Mapping[str, Any], payload: Mapping[str, Any]) -> SemanticReceipt:
        if not isinstance(reply, Mapping):
            raise AgentEffectUnknown("fixture reply is unconfirmed; readback required")
        _check_refusal(reply)
        wanted = {"kind": "receipt", "comparison": "atomic",
                  "operation_id": payload["operation_id"],
                  "launch_nonce": self._nonce, "sequence": payload["expected_sequence"] + 2,
                  "document_id": payload["document_id"], "job_status": payload["job_status"]}
        if (set(reply) != set(wanted)
                or any(type(reply[key]) is not type(value) or reply[key] != value
                       for key, value in wanted.items())):
            raise AgentEffectUnknown("fixture reply is unconfirmed; readback required")
        return SemanticReceipt(
            payload["operation_id"], "atomic",
            {key: reply[key] for key in ("document_id", "job_status", "sequence")})

    def cleanup(self) -> None:
        """Retire the command owner permanently and retry transport closure when needed."""
        self._terminal = True
        self._control.close()
