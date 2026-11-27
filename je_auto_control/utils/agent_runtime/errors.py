"""Typed failures for managed tasks, observations and control ownership."""
from typing import Any

from je_auto_control.utils.exception.exceptions import AutoControlException


class AgentTaskError(AutoControlException, ValueError):
    """A managed task cannot perform the requested operation."""


class AgentControlBusy(AgentTaskError):
    """Another task still owns the target's input or cleanup."""


class PresencePeerRefused(AgentTaskError):
    """One accepted presence connection was refused for its own peer; its listener stays open."""


class AgentObservationStale(AgentTaskError):
    """No action was dispatched because its observation is missing, expired or changed."""


class AgentEffectUnknown(AgentTaskError):
    """A dispatched command needs independent readback before any retry."""


class AgentHumanReview(AgentTaskError):
    """A dialog or unsaved-content gate requires explicit human review before continuing."""

    #: Verification reports the review was raised on, recorded with the waiting_user state.
    reports: tuple[dict[str, Any], ...] = ()
