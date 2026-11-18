"""Encode helper failures without disclosing memory or service details."""
from __future__ import annotations

from typing import Any, Mapping, NoReturn

from je_auto_control.utils.agent_runtime.errors import (
    AgentControlBusy, AgentTaskError, AgentHumanReview, AgentEffectUnknown, AgentObservationStale,
)
from je_auto_control.utils.process_memory.models import FailureReason, MemoryObservationError
from .service_status import ServiceFailure, ServiceQueryError

_ERROR_TYPES = {
    "AgentControlBusy": AgentControlBusy, "AgentHumanReview": AgentHumanReview,
    "AgentEffectUnknown": AgentEffectUnknown, "AgentObservationStale": AgentObservationStale,
}


def error_reply(request_id: str, error: Exception) -> dict[str, Any]:
    """Serialize memory and service failures as fixed reason codes."""
    if isinstance(error, ServiceQueryError):
        if not isinstance(error.reason, ServiceFailure):
            return {"id": request_id, "error_type": "AgentTaskError", "error": "invalid service failure"}
        return {"id": request_id, "error_type": "ServiceQueryError",
                "error": "service query failed", "service_reason": error.reason.value}
    if isinstance(error, MemoryObservationError):
        if not isinstance(error.reason, FailureReason):
            return {"id": request_id, "error_type": "AgentTaskError",
                    "error": "invalid memory failure"}
        return {"id": request_id, "error_type": "MemoryObservationError",
                "error": "memory observation failed", "memory_reason": error.reason.value}
    return {"id": request_id, "error": f"{type(error).__name__}: {error}",
            "error_type": type(error).__name__}


def raise_reply_error(reply: Mapping[str, Any]) -> NoReturn:
    """Reconstruct closed memory/service reasons without echoing malformed packets."""
    if reply.get("error_type") == "ServiceQueryError" or "service_reason" in reply:
        _raise_service_error(reply)
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


def _raise_service_error(reply: Mapping[str, Any]) -> NoReturn:
    if (set(reply) != {"id", "error_type", "error", "service_reason"}
            or reply.get("error_type") != "ServiceQueryError" or reply.get("error") != "service query failed"
            or not isinstance(reply.get("service_reason"), str)):
        raise AgentTaskError("native helper returned an invalid service failure")
    try:
        reason = ServiceFailure(reply["service_reason"])
    except ValueError:
        raise AgentTaskError("native helper returned an invalid service failure") from None
    raise ServiceQueryError(reason)
