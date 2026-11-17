"""Reviewable M0 routing profile: which background channel serves an operation, never desktop input.

This is the M0 deliverable of the background-operation plan in ``Progress.md``
and ``docs/process_memory_contract.md``: the profile, its result types and the
routing rule, as data that can be reviewed and tested. It reads nothing, opens
nothing and imports no input, wrapper or native code, so the existing desktop
foreground and input paths are not touched by it.

The routing rule is closed. :class:`Channel` lists the only interfaces a
background operation may use; desktop keyboard, mouse, focus and foreground
switching are deliberately not among them, and a route naming one is refused
when it is built. :func:`route` hands back a route only when its state says it
can be used; an unknown operation, or one whose adapter is still pending,
fails as ``UNSUPPORTED`` instead of falling back to anything else.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import FailureReason, MemoryObservationError, _identifier


class Channel(str, Enum):
    """The interfaces a background operation may use. Desktop input is not one of them."""

    OS_QUERY = "os_query"              # retained OS handle and its documented queries
    UIA_READ = "uia_read"              # UI Automation properties only: no Invoke, SetValue or focus
    MANAGED_DOM = "managed_dom"        # the existing WebRunner managed browser session
    MEMORY_READ = "memory_read"        # reviewed probe over the bounded read provider; never writes
    APPLICATION_API = "application_api"  # an application's official API, CLI or IPC
    OS_SERVICE = "os_service"          # one approved service's management interface
    STATE_READBACK = "state_readback"  # fresh state or artifact verification under runtime authority


class RouteState(str, Enum):
    """How far an operation's adapter has got; only the first two may be routed to."""

    EXISTING = "existing"              # an implementation already in the package serves it
    INJECTED_TESTS = "injected_tests"  # typed calls exist and are tested through injected functions only
    PENDING = "pending"                # not implemented; routing to it is unsupported


#: Names that must never appear as a route's channel: they are the desktop input path.
DESKTOP_INPUT = frozenset({"desktop_input", "keyboard", "mouse", "focus", "foreground"})

_ROUTABLE = frozenset({RouteState.EXISTING, RouteState.INJECTED_TESTS})


@dataclass(frozen=True)
class BackgroundRoute:
    """One row of the capability matrix: an operation, the channel that serves it, and its state."""

    operation: str
    label: str
    channel: Channel
    read_only: bool
    requirement: str
    state: RouteState

    def __post_init__(self) -> None:
        _identifier(self.operation)
        if str(getattr(self.channel, "value", self.channel)) in DESKTOP_INPUT or not isinstance(self.channel, Channel):
            raise MemoryObservationError(FailureReason.UNSUPPORTED)
        if not isinstance(self.state, RouteState) or not self.label or not self.requirement:
            raise MemoryObservationError(FailureReason.UNSUPPORTED)


@dataclass(frozen=True)
class BackgroundProfile:
    """The routes one platform offers; operations are unique."""

    platform: str
    routes: tuple[BackgroundRoute, ...]

    def __post_init__(self) -> None:
        _identifier(self.platform)
        names = [item.operation for item in self.routes]
        if not names or len(set(names)) != len(names):
            raise MemoryObservationError(FailureReason.UNSUPPORTED)

    def get(self, operation: str) -> BackgroundRoute | None:
        """The route for ``operation`` whatever its state, or ``None`` if the profile has none."""
        return next((item for item in self.routes if item.operation == operation), None)


def route(profile: BackgroundProfile, operation: str) -> BackgroundRoute:
    """The route that serves ``operation``; ``UNSUPPORTED`` when there is none or it is still pending.

    Never a fallback: an operation this profile cannot serve in the background
    is reported as unsupported, not handed to desktop input.
    """
    found = profile.get(operation)
    if found is None or found.state not in _ROUTABLE:
        raise MemoryObservationError(FailureReason.UNSUPPORTED)
    return found


#: The Windows capability matrix of ``docs/process_memory_contract.md``, as data.
WINDOWS_PROFILE = BackgroundProfile("windows", (
    BackgroundRoute("process.identity", "Process/session identity", Channel.OS_QUERY, True,
                    "Read/query/synchronize rights only; no privilege escalation", RouteState.INJECTED_TESTS),
    BackgroundRoute("ui.state", "UI state", Channel.UIA_READ, True,
                    "No Invoke, SetValue or focus change", RouteState.PENDING),
    BackgroundRoute("browser.state", "Browser state", Channel.MANAGED_DOM, True,
                    "Dedicated managed browser; no desktop input fallback", RouteState.EXISTING),
    BackgroundRoute("fixture.state", "Fixture semantic state", Channel.MEMORY_READ, True,
                    "Bounded query/read provider; no writes", RouteState.INJECTED_TESTS),
    BackgroundRoute("application.command", "Application command", Channel.APPLICATION_API, False,
                    "Must independently prove no foreground/focus/mouse/input interference", RouteState.PENDING),
    BackgroundRoute("os.service", "OS service operation", Channel.OS_SERVICE, False,
                    "Explicit service scope and independent status readback", RouteState.PENDING),
    BackgroundRoute("task.completion", "Completed background task", Channel.STATE_READBACK, True,
                    "Observation does not grant execution rights or replace a completion receipt", RouteState.PENDING),
))


__all__ = ["BackgroundProfile", "BackgroundRoute", "Channel", "DESKTOP_INPUT", "RouteState",
           "WINDOWS_PROFILE", "route"]
