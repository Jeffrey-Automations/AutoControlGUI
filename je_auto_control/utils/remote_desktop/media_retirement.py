"""Observable media retirement without confusing finalization with release."""
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.exception.control_signals import raise_caused_run_interruption


class Completion(Enum):
    """Acknowledgement of one independent retirement obligation."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class RetirementStatus:
    """A snapshot, never an instruction or authority to retry."""

    admission_closed: bool
    resources: Completion
    finalization: Completion
    retryable: bool = False
    failed_steps: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return (self.admission_closed
                and self.resources is Completion.CONFIRMED
                and self.finalization is Completion.CONFIRMED)


class RetirementOwner(Protocol):
    """An original owner retained by callers after failed retirement."""

    @property
    def retirement_status(self) -> RetirementStatus: ...

    def stop(self) -> None: ...


class MediaRetirementError(AutoControlException, RuntimeError):
    """Retirement is pending or uncertain; ``owner`` keeps its resources."""

    def __init__(self, owner: RetirementOwner) -> None:
        self.owner = owner
        self.status = owner.retirement_status
        super().__init__("media retirement incomplete: "
                         + ", ".join(self.status.failed_steps))


def require_retired(owner: RetirementOwner) -> None:
    """Preserve the ordinary stop contract only for confirmed completion."""
    if not owner.retirement_status.complete:
        raise MediaRetirementError(owner)


def raise_cleanup_failures(failures: list[BaseException]) -> None:
    """After independent cleanup, preserve control identity before ordinary errors."""
    for failure in failures:
        raise_caused_run_interruption(failure)
    if failures:
        raise failures[0]


@dataclass(frozen=True)
class _InterruptedOwners:
    owners: tuple[RetirementOwner, ...]


def interrupted_retirement_owners(error: BaseException) -> tuple[RetirementOwner, ...]:
    """Recover constructor cleanup owners without replacing a control signal."""
    retained = getattr(error, "_media_retirement_owners", None)
    return retained.owners if isinstance(retained, _InterruptedOwners) else ()


def preserve_interrupted_owner(owner: RetirementOwner, *failures: BaseException) -> None:
    """Attach an explicit handoff to the original signal before propagating it."""
    for failure in failures:
        try:
            raise_caused_run_interruption(failure)
        except BaseException as signal:
            owners = interrupted_retirement_owners(signal)
            if not any(item is owner for item in owners):
                owners += (owner,)
            setattr(signal, "_media_retirement_owners", _InterruptedOwners(owners))
            raise
