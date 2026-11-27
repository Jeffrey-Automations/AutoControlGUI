"""Trusted Android control leases require real device fencing and independent per-command settlement."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, ContextManager, Protocol

from je_auto_control.utils.agent_runtime.android_action_result import AndroidActionResult
from je_auto_control.utils.agent_runtime.android_commands import AndroidActionProposal
from je_auto_control.utils.agent_runtime.android_input_evidence import AndroidInputEvidence
from je_auto_control.utils.agent_runtime.android_scope import AndroidSnapshot
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.models import AgentTaskSpec
from je_auto_control.utils.agent_runtime.remote_journal import _token


@dataclass(frozen=True)
class AndroidCommandLease:
    """Host-only grant; device_fence must suppress old SDK writes after takeover, expiry or cancellation.

    A host-only lock, context manager, shell return or local process exit cannot implement that
    contract. No default provider is supplied. Settlement must independently certify this exact
    request ID, boot and epoch, released input and an empty queue of remote writes.

    ``dispatch``, when a provider supplies it, sends the command through the provider's own
    device-side writer (the helper's ``begin``) instead of a host ``adb shell input`` command, so
    the device itself enforces the epoch the command was begun under.
    """

    proposal: AndroidActionProposal = field(repr=False)
    request_id: str
    epoch: str
    device_fence: Callable[[], ContextManager[None]] = field(repr=False)
    checkpoint: Callable[[], None] = field(repr=False)
    settle: Callable[[AndroidActionResult], dict[str, Any]] = field(repr=False)
    dispatch: Callable[[str, dict[str, Any], float, Callable[[], None]], AndroidActionResult] | None = field(
        default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, AndroidActionProposal) or self.proposal.input_evidence is None:
            raise AgentTaskError("Android control lease requires a checked proposal")
        if not isinstance(self.request_id, str) or re.fullmatch("[0-9a-f]{32}", self.request_id) is None:
            raise AgentTaskError("Android control lease requires an exact per-command request identity")
        _token(self.epoch, "Android control epoch")
        if any(not callable(part) for part in (self.device_fence, self.checkpoint, self.settle)):
            raise AgentTaskError("Android control lease requires trusted device-fence and settlement providers")
        if self.dispatch is not None and not callable(self.dispatch):
            raise AgentTaskError("Android control lease dispatch must be a trusted device-side writer")


class AndroidControlProvider(Protocol):
    """Explicit trusted host service contract; standard ADB is not assumed to supply any of these guarantees."""

    def ready(self, snapshot: AndroidSnapshot, evidence: AndroidInputEvidence, spec: AgentTaskSpec) -> tuple[bool, str]:
        """Prove live physical activity/held-input state, idle policy and global-monitor review without input."""

    def checkpoint(self, binding: tuple[str, str, int]) -> None:
        """Check live device/app authority and physical takeover; never dispatch or release input here."""

    def lease(self, proposal: AndroidActionProposal, request_id: str) -> AndroidCommandLease:
        """Recheck presence/idle/held input and global monitors; fence this exact proposal/request without input."""

    def set_takeover_handler(self, handler: Callable[[], None]) -> None:
        """Observe trusted physical activity across SDK operations, excluding injected events."""
