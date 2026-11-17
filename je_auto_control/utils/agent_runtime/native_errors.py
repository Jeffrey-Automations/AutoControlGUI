"""Encode helper failures without disclosing memory details and preserve closed reason codes."""
from __future__ import annotations

from typing import Any, Mapping, NoReturn

from je_auto_control.utils.agent_runtime.errors import (
    AgentControlBusy, AgentTaskError, AgentHumanReview, AgentEffectUnknown, AgentObservationStale,
)
from je_auto_control.utils.process_memory.models import FailureReason, MemoryObservationError

_ERROR_TYPES = {
    "AgentControlBusy": AgentControlBusy, "AgentHumanReview": AgentHumanReview,
    "AgentEffectUnknown": AgentEffectUnknown, "AgentObservationStale": AgentObservationStale,
}


def error_reply(request_id: str, error: Exception) -> dict[str, Any]:
    """Serialize memory failures only as fixed reason codes; preserve other helper errors."""
    if isinstance(error, MemoryObservationError):
        if not isinstance(error.reason, FailureReason):
            return {"id": request_id, "error_type": "AgentTaskError",
                    "error": "invalid memory failure"}
        return {"id": request_id, "error_type": "MemoryObservationError",
                "error": "memory observation failed", "memory_reason": error.reason.value}
    return {"id": request_id, "error": f"{type(error).__name__}: {error}",
            "error_type": type(error).__name__}


def raise_reply_error(reply: Mapping[str, Any]) -> NoReturn:
    """Reconstruct only known memory reasons and never echo malformed memory packets."""
    if reply.get("error_type") == "MemoryObservationError" or "memory_reason" in reply:
        if (set(reply) != {"id", "error_type", "error", "memory_reason"}
                or reply.get("error_type") != "MemoryObservationError"
                or reply.get("error") != "memory observation failed"
                or not isinstance(reply.get("memory_reason"), str)):
            raise AgentTaskError("native helper returned an invalid memory failure")
        try:
            reason = FailureReason(reply["memory_reason"])
        except ValueError:
            raise AgentTaskError("native helper returned an invalid memory failure") from None
        raise MemoryObservationError(reason)
    raise _ERROR_TYPES.get(str(reply.get("error_type")), AgentTaskError)(str(reply["error"]))
