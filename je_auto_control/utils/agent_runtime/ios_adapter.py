"""Bridge a WebDriverAgent session into the owned remote worker only with an explicit trusted control provider.

WebDriverAgent offers no device-side fence, generation or idle guarantee, so nothing here assumes
one: without a configured :class:`IosControlProvider` readiness is withheld before any WDA call,
and a lease must bring its own device-side ``dispatch`` (there is no host fallback writer, unlike
Android's checked ``adb`` path). The adapter reads only bounded metadata (the foreground app, its
state, the window size and orientation), refuses an action whose metadata changed since the
observation, and binds every call to a fresh per-command request identity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import threading
import time
import uuid
from typing import Any, Callable, ContextManager, Protocol

from je_auto_control.utils.agent_runtime.context import current_operation
from je_auto_control.utils.agent_runtime.errors import AgentObservationStale, AgentTaskError
from je_auto_control.utils.agent_runtime.models import AgentTaskSpec, detached
from je_auto_control.utils.agent_runtime.remote_effect import PreparedRemoteAction, remote_scope_key
from je_auto_control.utils.agent_runtime.remote_journal import _token, device_identity

IOS_INPUT_TOOLS = frozenset({"AC_ios_tap", "AC_ios_swipe", "AC_ios_press_key"})
_KEYS = frozenset({"home", "volumeUp", "volumeDown"})
_BUNDLE = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_FOREGROUND = 4  # XCUIApplicationStateRunningForeground


@dataclass(frozen=True)
class IosSnapshot:
    """Bounded foreground-app metadata; it proves no device identity, which the provider must."""

    physical_id: str
    bundle_id: str
    pid: int
    state: int
    size: tuple[int, int]
    orientation: str

    def identity(self) -> dict[str, Any]:
        """The observation identity a task sees; no element values or screen content."""
        return {"platform": "ios", "physical_id": self.physical_id, "bundle_id": self.bundle_id,
                "app_state": self.state, "display_size": list(self.size), "orientation": self.orientation}


@dataclass(frozen=True)
class IosActionProposal:
    """One checked finite call; repr excludes arguments and it never grants input authority."""

    snapshot: IosSnapshot
    name: str
    arguments: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class IosCommandLease:
    """Host-only grant from a trusted provider; ``dispatch`` is the provider's own device-side writer."""

    proposal: IosActionProposal = field(repr=False)
    request_id: str
    epoch: str
    device_fence: Callable[[], ContextManager[None]] = field(repr=False)
    checkpoint: Callable[[], None] = field(repr=False)
    dispatch: Callable[[str, dict[str, Any], float, Callable[[], None]], dict[str, Any]] = field(repr=False)
    settle: Callable[[], dict[str, Any]] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, IosActionProposal):
            raise AgentTaskError("iOS control lease requires a checked proposal")
        if not isinstance(self.request_id, str) or re.fullmatch("[0-9a-f]{32}", self.request_id) is None:
            raise AgentTaskError("iOS control lease requires an exact per-command request identity")
        _token(self.epoch, "iOS control epoch")
        if any(not callable(part) for part in (self.device_fence, self.checkpoint, self.dispatch, self.settle)):
            raise AgentTaskError("iOS control lease requires trusted fence, dispatch and settlement providers")


class IosControlProvider(Protocol):
    """Explicit trusted host service contract; WebDriverAgent is not assumed to supply any of it."""

    def ready(self, snapshot: IosSnapshot, spec: AgentTaskSpec) -> tuple[bool, str]:
        """Prove the physical device identity, live physical activity/idle state and held input, without input."""

    def checkpoint(self, physical_id: str) -> None:
        """Check live device/app authority and physical takeover; never dispatch or release input here."""

    def lease(self, proposal: IosActionProposal, request_id: str) -> IosCommandLease:
        """Fence old writers on the device and bind this exact proposal and request."""

    def set_takeover_handler(self, handler: Callable[[], None]) -> None:
        """Observe trusted physical activity, excluding injected events."""


def _bounded(function: Callable[[], Any], deadline: float) -> Any:
    """Run one blocking SDK read; a late result is discarded and reported as unavailable."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AgentTaskError("iOS metadata deadline exhausted")
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["value"] = function()
        except Exception:  # noqa: BLE001  # reason: SDK errors are reported without their text
            outcome["error"] = True

    worker = threading.Thread(target=run, name="IosMetadataRead", daemon=True)
    worker.start()
    worker.join(remaining)
    if worker.is_alive() or "value" not in outcome:
        raise AgentTaskError("iOS WebDriverAgent metadata is unavailable")
    return outcome["value"]


def check_ios_arguments(name: str, arguments: dict[str, Any]) -> None:
    """Accept only the closed argument shapes of the reviewed iOS input tools."""
    fields = {"AC_ios_tap": {"x", "y"}, "AC_ios_swipe": {"x1", "y1", "x2", "y2", "duration_s"},
              "AC_ios_press_key": {"key"}}
    if name not in fields or not isinstance(arguments, dict) or set(arguments) - fields[name]:
        raise AgentTaskError("iOS action has an unreviewed tool or argument")
    if name == "AC_ios_press_key":
        key = arguments.get("key")
        if not isinstance(key, str) or key not in _KEYS:
            raise AgentTaskError("iOS key is outside the finite hardware-button set")
        return
    _check_points(arguments, ("x", "y") if name == "AC_ios_tap" else ("x1", "y1", "x2", "y2"))
    if name == "AC_ios_swipe":
        _check_duration(arguments.get("duration_s", 0.5))


def _check_points(arguments: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        value = arguments.get(key)
        if type(value) is not int or not 0 <= value <= 16383:
            raise AgentTaskError("iOS coordinates must be integers within the reviewed bounds")


def _check_duration(duration: Any) -> None:
    if type(duration) not in (int, float) or not 0 < duration <= 2:
        raise AgentTaskError("iOS swipe duration must be within the reviewed bounds")


class IosDeviceSession:
    """Bounded metadata reads over one host-bound WDA client for one host-selected bundle."""

    def __init__(self, client: Any, *, physical_id: str, bundle_id: str) -> None:
        _token(physical_id, "iOS device identity")
        if not isinstance(bundle_id, str) or _BUNDLE.fullmatch(bundle_id) is None or len(bundle_id) > 255:
            raise AgentTaskError("iOS bundle identifier is invalid")
        self._client, self._binding = client, (physical_id, bundle_id)

    @property
    def binding(self) -> tuple[str, str]:
        """The host-selected device identity and bundle."""
        return self._binding

    def inspect(self, deadline: float, check: Callable[[], None]) -> IosSnapshot:
        """Read the foreground app, its state, the window size and orientation within ``deadline``."""
        physical_id, bundle_id = self._binding
        check()
        current = _bounded(self._client.app_current, deadline)
        state = _bounded(lambda: self._client.app_state(bundle_id), deadline)
        size = _bounded(self._client.window_size, deadline)
        orientation = _bounded(lambda: self._client.orientation, deadline)
        check()
        if not isinstance(current, dict) or current.get("bundleId") != bundle_id:
            raise AgentObservationStale("iOS foreground app is not the host-bound bundle")
        numbers = (state.get("value") if isinstance(state, dict) else None, current.get("pid"),
                   getattr(size, "width", None), getattr(size, "height", None))
        whole = [item for item in numbers if type(item) is int]
        if len(whole) != 4 or not isinstance(orientation, str) or len(orientation) > 32:
            raise AgentTaskError("iOS WebDriverAgent metadata is malformed")
        value, pid, width, height = whole
        return IosSnapshot(physical_id, bundle_id, pid, value, (width, height), orientation)


class IosRemoteAdapter:
    """Internal WDA adapter; a missing trusted control provider always withholds readiness."""

    def __init__(self, session: IosDeviceSession, *, control: IosControlProvider | None = None) -> None:
        self._session, self._control = session, control
        self._spec: AgentTaskSpec | None = None
        self._observed: IosSnapshot | None = None

    @property
    def device(self) -> dict[str, str]:
        """Bind remote ownership to the host-selected physical device."""
        return device_identity("ios", self._session.binding[0])

    def set_takeover_handler(self, handler: Callable[[], None]) -> None:
        """Forward only the configured provider's trusted physical-activity notices."""
        if self._control is not None:
            self._control.set_takeover_handler(handler)

    def checkpoint(self) -> None:
        """No local fallback can certify remote activity, held input or device fencing."""
        if self._control is None:
            raise AgentTaskError("iOS requires a trusted device-control provider")
        self._control.checkpoint(self._session.binding[0])

    def _context(self) -> tuple[AgentTaskSpec, Callable[[], None]]:
        context = current_operation()
        if context is None:
            raise AgentTaskError("iOS adapter requires its explicitly managed operation scope")
        if (self._spec is not None
                and remote_scope_key(context.spec.to_dict()) != remote_scope_key(self._spec.to_dict())):
            raise AgentTaskError("iOS adapter cannot replace its configured task scope")
        return context.spec, context.checkpoint

    def ready(self, spec: AgentTaskSpec) -> tuple[bool, str]:
        """Validate exact host bundle/tools; require a provider before any WDA call."""
        current, check = self._context()
        if remote_scope_key(current.to_dict()) != remote_scope_key(spec.to_dict()):
            raise AgentTaskError("iOS readiness does not match its managed task")
        if tuple(spec.apps) != (self._session.binding[1],) or not set(spec.allowed_tools) <= IOS_INPUT_TOOLS:
            return False, "iOS requires its exact host-bound bundle and finite reviewed input tools"
        if self._control is None:
            return False, "iOS trusted device fencing/presence/settlement provider is not configured"
        snapshot = self._session.inspect(time.monotonic() + spec.budget.action_seconds, check)
        if snapshot.state != _FOREGROUND:
            return False, "iOS host-bound bundle is not in the foreground"
        ready, reason = self._control.ready(snapshot, spec)
        if not isinstance(ready, bool) or not isinstance(reason, str):
            raise AgentTaskError("iOS control provider returned invalid readiness")
        check()
        if ready:
            self._spec, self._observed = spec, None
        return ready, reason

    def observe(self) -> dict[str, Any]:
        """Publish bounded app metadata only; never element values, text or screenshots."""
        spec, check = self._context()
        if self._spec is None:
            raise AgentTaskError("iOS adapter is not ready")
        self.checkpoint()
        self._observed = None
        snapshot = self._session.inspect(time.monotonic() + spec.budget.action_seconds, check)
        self._observed = snapshot
        return {"identity": snapshot.identity(), "elements": [], "text": "", "semantic_observation": False,
                "text_redacted": True}

    def prepare(self, name: str, arguments: dict[str, Any]) -> PreparedRemoteAction:
        """Refuse stale metadata and return one finite call bound to a fresh trusted device lease."""
        spec, check = self._context()
        if self._spec is None or self._observed is None or self._control is None:
            raise AgentObservationStale("iOS action requires a current checked observation")
        if name not in spec.allowed_tools:
            raise AgentTaskError("iOS tool is outside its configured task")
        arguments = detached(arguments)
        check_ios_arguments(name, arguments)
        deadline = time.monotonic() + spec.budget.action_seconds
        snapshot = self._session.inspect(deadline, check)
        if snapshot != self._observed:
            raise AgentObservationStale("iOS app, state, size or orientation changed since observation")
        proposal = IosActionProposal(snapshot, name, arguments)
        request_id = uuid.uuid4().hex
        lease = self._control.lease(proposal, request_id)
        if not isinstance(lease, IosCommandLease) or lease.proposal != proposal or lease.request_id != request_id:
            raise AgentTaskError("iOS control lease does not match its exact prepared command")
        check()
        self._observed = None
        return _prepared_call(self.device, lease, deadline, check)


def _prepared_call(device: dict[str, str], lease: IosCommandLease, deadline: float,
                   check: Callable[[], None]) -> PreparedRemoteAction:
    invoked = [False]

    def checkpoint() -> None:
        check()
        lease.checkpoint()
        if time.monotonic() >= deadline:
            raise AgentTaskError("iOS action deadline exhausted")

    def invoke() -> dict[str, Any]:
        if invoked[0]:
            raise AgentTaskError("iOS prepared commands cannot be replayed")
        invoked[0] = True
        checkpoint()
        with lease.device_fence():
            checkpoint()
            result = lease.dispatch(lease.proposal.name, lease.proposal.arguments, deadline, checkpoint)
        if not isinstance(result, dict) or set(result) != {"ios_phase", "may_have_effect"}:
            raise AgentTaskError("iOS device writer returned an unknown result")
        return result

    def settle() -> dict[str, Any]:
        if not invoked[0]:
            raise AgentTaskError("iOS settlement has no command result")
        proof = lease.settle()
        if (not isinstance(proof, dict)
                or set(proof) != {"device", "epoch", "inputs_released", "queue_empty", "request_id"}
                or proof["request_id"] != lease.request_id):
            raise AgentTaskError("iOS settlement does not match this command request")
        return {key: value for key, value in proof.items() if key != "request_id"}

    return PreparedRemoteAction(device, lease.epoch, invoke, settle)
