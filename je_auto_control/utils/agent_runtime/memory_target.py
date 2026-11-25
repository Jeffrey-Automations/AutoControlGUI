"""Bind a managed semantic target to one reviewed reader and background command owner."""
from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Mapping, Protocol

from je_auto_control.utils.agent_runtime.capture_checkpoint import capture_checkpoint
from je_auto_control.utils.agent_runtime.context import TaskOperation, authorization_key, current_operation
from je_auto_control.utils.agent_runtime.errors import AgentObservationStale, AgentTaskError
from je_auto_control.utils.agent_runtime.models import AgentTaskSpec
from je_auto_control.utils.agent_runtime.policy import TaskPolicy
from je_auto_control.utils.agent_runtime.semantic_target import (
    SemanticReceipt, SemanticSnapshot, SemanticTarget, _identifier,
)
from je_auto_control.utils.process_memory.models import (
    FailureReason, MemoryObservationError, ObservationFailure, ProcessIdentity, ReviewedProbe,
)
from je_auto_control.utils.process_memory.reader import ProcessMemoryReader


@dataclass(frozen=True)
class MemoryBinding:
    """Host-selected process, probe and field scope; never constructed from task JSON."""

    target_id: str
    identity: ProcessIdentity
    probe: ReviewedProbe
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.target_id)
        object.__setattr__(self, "fields", tuple(self.fields))
        if (not self.fields or len(set(self.fields)) != len(self.fields)
                or not set(self.fields) <= set(self.probe.fields)):
            raise MemoryObservationError(FailureReason.SCOPE_DENIED)


class BackgroundCommands(Protocol):
    """Reviewed operation owner; the reader grants no command authority or atomicity."""

    def ready(self, spec: AgentTaskSpec) -> tuple[bool, str]:
        """Validate this task's operation scope without granting additional rights."""

    def perform_grounded(self, name: str, arguments: Mapping[str, Any], *,
                         expected: SemanticSnapshot, operation_id: str) -> SemanticReceipt:
        """Compare expected state at commit or explicitly report non-atomic execution."""

    def cleanup(self) -> None:
        """Retire owned resources, raising if retirement is unconfirmed."""


class MemorySemanticTarget(SemanticTarget):
    """Serialize one task's bounded reads, grounded operations and retryable retirement."""

    def __init__(self, binding: MemoryBinding, reader: ProcessMemoryReader,
                 commands: BackgroundCommands) -> None:
        self._binding, self._reader, self._commands = binding, reader, commands
        self._spec: AgentTaskSpec | None = None
        self._owner: tuple[str, str, str | None] | None = None
        self._terminal = False
        self._lock = threading.RLock()

    def ready(self, spec: AgentTaskSpec) -> tuple[bool, str]:
        """Pin the managed task before allowing any reader acquisition."""
        with self._lock:
            operation = current_operation()
            if self._spec is not None and self._spec != spec:
                raise AgentTaskError("memory target is already bound to a different task")
            if (self._terminal or operation is None or operation.spec != spec
                    or spec.target != self._binding.target_id):
                raise AgentTaskError("memory target requires its bound managed task")
            if self._spec is not None and authorization_key(operation.owner) != self._owner:
                raise AgentTaskError("memory target belongs to a different owner")
            operation.checkpoint()
            result = self._commands.ready(spec)
            operation.checkpoint()
            if result[0] is True:
                self._spec = spec
                self._owner = authorization_key(operation.owner)
            return result

    def _validate(self) -> TaskOperation:
        operation = current_operation()
        if (self._terminal or self._spec is None or operation is None
                or operation.spec != self._spec):
            raise AgentTaskError("memory target is outside its live managed task")
        if authorization_key(operation.owner) != self._owner:
            raise AgentTaskError("memory target belongs to a different owner")
        return operation

    def _checkpoint(self) -> None:
        self._validate().checkpoint()
        if self._reader.pending_cleanup:
            raise MemoryObservationError(FailureReason.CLEANUP_FAILED)

    def _validate_read(self) -> None:
        self._validate()

    def observe(self) -> dict[str, Any]:
        """Publish only successful allowlisted semantic fields; preserve explicit read failures."""
        with self._lock:
            self._checkpoint()
            binding = self._binding
            result = self._reader.observe(binding.identity, binding.probe, binding.fields,
                                          target_id=binding.target_id, checkpoint=self._checkpoint,
                                          poll=capture_checkpoint(self._validate_read, self._checkpoint))
            if isinstance(result, ObservationFailure):
                raise MemoryObservationError(result.reason)
            return SemanticSnapshot.from_memory(result).to_dict()

    def perform_grounded(self, name: str, arguments: Mapping[str, Any], *,
                         expected: SemanticSnapshot, operation_id: str) -> SemanticReceipt:
        """Recheck policy and readback; the command owner must still compare at commit."""
        with self._lock:
            self._checkpoint()
            operation = current_operation()
            if operation is None:
                raise AgentTaskError("memory command requires a managed task")
            TaskPolicy(operation.spec).check(name, arguments)
            _identifier(operation_id)
            current = SemanticSnapshot.from_dict(self.observe())
            if not current.same_state(expected):
                raise AgentObservationStale("memory target changed before dispatch")
            self._checkpoint()
            receipt = self._commands.perform_grounded(
                name, arguments, expected=expected, operation_id=operation_id)
            self._checkpoint()
            if not isinstance(receipt, SemanticReceipt) or receipt.operation_id != operation_id:
                raise AgentTaskError("memory command did not confirm this operation")
            return receipt

    def perform(self, _name: str, _arguments: Mapping[str, Any]) -> None:
        """Refuse ungrounded dispatch even for a host-selected adapter."""
        raise AgentTaskError("memory commands require grounded dispatch")

    def cleanup(self) -> None:
        """Retire permanently; failed resources remain owned for subsequent cleanup calls."""
        with self._lock:
            self._terminal = True
            try:
                self._commands.cleanup()
            finally:
                if not self._reader.close_pending():
                    raise MemoryObservationError(FailureReason.CLEANUP_FAILED)
