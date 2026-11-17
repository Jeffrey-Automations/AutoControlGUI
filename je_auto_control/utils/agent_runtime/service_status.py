"""Represent the latest SCM service report without granting operation authority."""
from dataclasses import dataclass
from enum import Enum, IntEnum

from .errors import AgentTaskError


class ServiceFailure(Enum):
    """Closed failure reasons safe to expose without native exception messages."""

    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED = "unsupported"
    ACCESS_DENIED = "access_denied"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    INVALID_STATUS = "invalid_status"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    RETIRED = "retired"
    BUSY = "busy"
    CLEANUP_FAILED = "cleanup_failed"


class ServiceQueryError(AgentTaskError):
    """A service query failed with a fixed, non-sensitive reason."""

    def __init__(self, reason: ServiceFailure) -> None:
        self.reason = reason
        super().__init__(reason.value)


class ServiceState(IntEnum):
    """Documented SERVICE_STATUS_PROCESS state values."""

    STOPPED = 1
    START_PENDING = 2
    STOP_PENDING = 3
    RUNNING = 4
    CONTINUE_PENDING = 5
    PAUSE_PENDING = 6
    PAUSED = 7


@dataclass(frozen=True)
class ServiceStatus:
    """Best-effort status; progress_checkpoint is not a state revision.

    process_id is diagnostic only and never grants process access or identity.
    controls_accepted describes a report, not the caller's operation permissions.
    """

    state: ServiceState
    service_type: int
    controls_accepted: int
    win32_exit_code: int
    service_specific_exit_code: int
    progress_checkpoint: int
    wait_hint_ms: int
    process_id: int | None
    service_flags: int

    def to_dict(self) -> dict[str, str | int | None]:
        """Return diagnostic fields with an explicit consistency limitation."""
        return {
            "state": self.state.name.lower(), "consistency": "best_effort",
            "service_type": self.service_type, "controls_accepted": self.controls_accepted,
            "win32_exit_code": self.win32_exit_code,
            "service_specific_exit_code": self.service_specific_exit_code,
            "progress_checkpoint": self.progress_checkpoint, "wait_hint_ms": self.wait_hint_ms,
            "process_id": self.process_id, "service_flags": self.service_flags,
        }
