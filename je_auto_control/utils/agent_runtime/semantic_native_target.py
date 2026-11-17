"""Owned semantic helper proxy that refuses every desktop input event."""
from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Mapping, Sequence

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.models import AgentTaskSpec
from je_auto_control.utils.agent_runtime.native_target import NativeDesktopTarget
from je_auto_control.utils.agent_runtime.semantic_target import (
    SemanticReceipt, SemanticSnapshot, SemanticTarget, _report,
)


class NativeSemanticTarget(NativeDesktopTarget, SemanticTarget):
    """Trusted host code supplies the reviewed helper and its explicit resource lock."""

    _display_helper: ClassVar[bool] = False

    def __init__(self, *, argv: Sequence[str], resource_path: Path,
                 profile: dict[str, Any] | None = None) -> None:
        super().__init__(argv=argv, resource_path=resource_path, recovery_probe=lambda: None, profile=profile)

    @property
    def supports_readonly_completion(self) -> bool:
        """Do not claim the desktop/browser read-only helper contract."""
        return False

    def _requires_presence(self, spec: AgentTaskSpec) -> bool:
        return False

    def _input(self, event: dict[str, Any], *, cleanup: bool = False) -> None:
        raise AgentTaskError("semantic helpers cannot emit desktop input")

    def _supports_bootstrap(self, reply: Any) -> bool:
        if not super()._supports_bootstrap(reply):
            return False
        version = reply.get("semantic")
        if type(version) is not int or version != 1:
            return False
        if self.observation_sources:
            return (type(reply.get("semantic_report")) is int and reply["semantic_report"] == 1
                    and reply.get("semantic_sources") == list(self.observation_sources))
        return "semantic_report" not in reply and "semantic_sources" not in reply

    def perform(self, name: str, arguments: dict[str, Any]) -> Any:
        """Refuse legacy dispatch without an expected semantic snapshot."""
        raise AgentTaskError("semantic commands require grounded dispatch")

    def perform_grounded(self, name: str, arguments: Mapping[str, Any], *,
                         expected: SemanticSnapshot, operation_id: str) -> SemanticReceipt:
        """Send expected state and journal identity under the existing live helper deadline."""
        return self._send_grounded(name, arguments, expected.to_dict(), operation_id)

    def perform_observed(self, name: str, arguments: Mapping[str, Any], *,
                         observation: Mapping[str, Any], operation_id: str) -> SemanticReceipt:
        """Preserve every source across IPC; the worker repeats the complete-report gate."""
        if self.observation_sources:
            report = _report(self, observation)
            report.require_grounding()
            return self._send_grounded(name, arguments, report.to_dict(), operation_id)
        return super().perform_observed(name, arguments, observation=observation, operation_id=operation_id)

    def _send_grounded(self, name: str, arguments: Mapping[str, Any],
                       expected: Mapping[str, Any], operation_id: str) -> SemanticReceipt:
        reply = self._request("perform_grounded", {"tool": name, "arguments": dict(arguments),
                              "expected": dict(expected), "operation_id": operation_id})
        receipt = SemanticReceipt.from_dict(reply)
        if receipt.operation_id != operation_id:
            raise AgentTaskError("semantic helper replied for another operation")
        return receipt

    def cleanup(self) -> None:
        """Ask a live helper to release its resources before proving process retirement."""
        channel = self._channel
        if channel is not None and not channel.retired:
            reply = channel.request("cleanup", {"keys": [], "buttons": []}, timeout=3,
                                    check=lambda: None, on_event=self._input)
            if (not isinstance(reply, dict) or set(reply) != {"cleaned"}
                    or reply["cleaned"] is not True):
                raise AgentTaskError("semantic helper cleanup is unconfirmed")
        super().cleanup()
