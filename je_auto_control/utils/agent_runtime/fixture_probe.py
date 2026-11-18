"""Own bounded static fixture inspections through shutdown and failed helper retirement."""
from __future__ import annotations

from dataclasses import dataclass, field
import sys
import threading
from typing import Any

from .errors import AgentControlBusy, AgentTaskError
from .owned_channel_factory import HelperChannel, owned_channel
from .semantic_worker import refuse_input
from .target_config import AgentTargetProfile
from ..exception.cancellation import cancellation_checkpoint
from ..exception.exceptions import AutoControlException
from ..rbac.deferred import DeferredAuthorization

_CAPACITY = threading.BoundedSemaphore(2)
_BOOTSTRAP_TIMEOUT = 15.0
_INSPECTION_TIMEOUT = 10.0


def check_management(authority: DeferredAuthorization) -> None:
    """Refresh the captured host manager without requiring desktop input authority."""
    cancellation_checkpoint()
    try:
        with authority.context_scope() as owner:
            if owner is not None and not owner.allows("manage_hosts"):
                raise AgentTaskError("fixture inspection requires host management")
    except (AutoControlException, OSError, ValueError, TypeError):
        raise AgentTaskError("fixture inspection authority is unavailable") from None


@dataclass(eq=False)
class _Inspection:
    name: str
    stopped: threading.Event = field(default_factory=threading.Event)
    channel: HelperChannel | None = None
    active: bool = True


def _report(raw: Any, profile: AgentTargetProfile) -> dict[str, Any]:
    expected = {"status": "static_artifacts_ready", "config_sha256": profile.settings["config_sha256"],
                "target": profile.name, "native_evidence": "not_recorded", "fixture_execution": "not_run"}
    if not isinstance(raw, dict) or set(raw) != set(expected) | {"checked_bytes"}:
        raise AgentTaskError("invalid fixture inspection response")
    checked = raw["checked_bytes"]
    if (any(raw[key] != value for key, value in expected.items())
            or type(checked) is not int or not 0 < checked <= (1 << 20) - 72):
        raise AgentTaskError("invalid fixture inspection response")
    return {**expected, "checked_bytes": checked}


class FixtureProbes:
    """Retain each capacity reservation until construction, work and retirement have settled."""

    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self._closed = False
        self._runs: dict[str, _Inspection] = {}

    def check(self) -> None:
        """Refuse publication or new work after shutdown begins."""
        with self._mutex:
            if self._closed:
                raise AgentTaskError("fixture inspections are closed")

    def _reserve(self, name: str) -> _Inspection:
        with self._mutex:
            if self._closed:
                raise AgentTaskError("fixture inspections are closed")
            # pylint: disable-next=consider-using-with  # reason: capacity follows retained helper ownership across calls
            if name in self._runs or not _CAPACITY.acquire(blocking=False):
                raise AgentControlBusy("fixture inspection capacity is still owned")
            run = _Inspection(name)
            self._runs[name] = run
            return run

    def probe(self, profile: AgentTargetProfile, authority: DeferredAuthorization) -> dict[str, Any]:
        """Inspect only host-pinned files in a separate helper, never constructing a native target."""
        if profile.kind != "fixture":
            raise AgentTaskError("fixture inspection requires a fixture profile")
        check_management(authority)
        run = self._reserve(profile.name)

        def check() -> None:
            if run.stopped.is_set():
                raise AgentTaskError("fixture inspection was stopped")
            check_management(authority)

        try:
            settings = profile.settings
            argv = (sys.executable, "-I", "-u", "-m", "je_auto_control.utils.agent_runtime.fixture_worker",
                    "--config", settings["config_path"], "--config-sha256", settings["config_sha256"], "--inspect")
            channel = owned_channel(argv)
            with self._mutex:
                run.channel = channel
            check()
            bootstrap = channel.request("bootstrap", {}, timeout=_BOOTSTRAP_TIMEOUT, check=check, on_event=refuse_input)
            if (bootstrap != {"protocol": 1, "fixture_inspection": 1} or not isinstance(bootstrap, dict)
                    or any(type(value) is not int for value in bootstrap.values())):
                raise AgentTaskError("fixture inspection bootstrap is incompatible")
            raw = channel.request("inspect_fixture", {}, timeout=_INSPECTION_TIMEOUT,
                                  check=check, on_event=refuse_input)
            check()
            result = _report(raw, profile)
        except BaseException as error:
            try:
                self._finish(run)
            except BaseException as cleanup:
                raise error from cleanup
            raise
        self._finish(run)
        check()
        return result

    def _finish(self, run: _Inspection) -> None:
        with self._mutex:
            run.active = False
        self._retire(run)

    def _retire(self, run: _Inspection) -> None:
        with self._mutex:
            channel = run.channel
        if channel is not None:
            channel.close()
            if not channel.retired:
                raise AgentControlBusy("fixture inspection helper has not retired")
        with self._mutex:
            settled = run.channel is None or run.channel.retired
            if settled and not run.active and self._runs.get(run.name) is run:
                del self._runs[run.name]
                _CAPACITY.release()

    def close(self) -> None:
        """Seal admissions and retain unresolved owners so runtime shutdown can be retried."""
        with self._mutex:
            self._closed = True
            runs = list(self._runs.values())
            for run in runs:
                run.stopped.set()
        failures = []
        for run in runs:
            try:
                self._retire(run)
            except (AutoControlException, OSError, RuntimeError) as error:
                failures.append(error)
        with self._mutex:
            pending = bool(self._runs)
        if failures or pending:
            cause = failures[0] if failures else None
            raise AgentControlBusy("fixture inspection ownership has not retired") from cause
