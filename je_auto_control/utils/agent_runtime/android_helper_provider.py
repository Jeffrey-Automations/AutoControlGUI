"""The trusted Android control provider: device-side fencing and settlement through the helper.

Every lease fences the device into a fresh epoch, so a command can run only under the lease that
began it; a physical event, a cancellation or a failed dispatch fences again, which stops a
command that is still injecting and turns every older queued one into ``fenced``. Settlement is
the helper's own account of that exact request, boot and epoch. Readiness requires the physical
input stream to be healthy and quiet for the idle window; an unknown source is never idle.
"""
from __future__ import annotations

from contextlib import contextmanager
import secrets
import threading
import time
from typing import Any, Callable, Iterator

from je_auto_control.utils.agent_runtime.android_action_result import AndroidActionResult
from je_auto_control.utils.agent_runtime.android_commands import AndroidActionProposal
from je_auto_control.utils.agent_runtime.android_control import AndroidCommandLease
from je_auto_control.utils.agent_runtime.android_helper_client import AndroidHelperClient, helper_command
from je_auto_control.utils.agent_runtime.android_input_evidence import AndroidInputEvidence
from je_auto_control.utils.agent_runtime.android_scope import AndroidSnapshot
from je_auto_control.utils.agent_runtime.errors import AgentControlBusy, AgentTaskError
from je_auto_control.utils.agent_runtime.models import AgentTaskSpec
from je_auto_control.utils.agent_runtime.remote_journal import device_identity

_TERMINAL = {"completed": "input_returned", "failed": "input_failed", "fenced": "input_failed"}
_POLL = 0.05


class HelperControlProvider:
    """Explicit host-configured provider; it owns the physical source and the device epoch it set."""

    def __init__(self, client: AndroidHelperClient, source: Any, *, idle_seconds: float = 60,
                 timeout: float = 5, clock: Callable[[], float] = time.monotonic) -> None:
        if isinstance(idle_seconds, bool) or not isinstance(idle_seconds, (int, float)) or not 0 < idle_seconds <= 3600:
            raise AgentTaskError("Android idle window must be between zero and one hour")
        self._client, self._source, self._idle = client, source, idle_seconds
        self._timeout, self._clock = timeout, clock
        self._lock = threading.Lock()
        self._handler: Callable[[], None] | None = None
        self._helper: tuple[str, str] | None = None
        self._active = False
        self._epoch: str | None = None
        self._source.set_handler(self._physical)

    # -- physical activity -------------------------------------------------------------------

    def set_takeover_handler(self, handler: Callable[[], None]) -> None:
        """Forward physical-activity notices to the runtime, after the device is fenced."""
        with self._lock:
            self._handler = handler

    def _physical(self) -> None:
        with self._lock:
            self._active = True
            handler = self._handler
        try:
            self._fence_quietly()
        finally:
            if handler is not None:
                handler()

    def _fence_quietly(self) -> None:
        """Fence without raising over the caller's own error; an unconfirmed fence refuses every later lease."""
        try:
            self._fence(lambda: None)
        except AgentTaskError:
            with self._lock:
                self._active = True  # an old writer may still run: only a new readiness check can clear this

    def _fence(self, check: Callable[[], None]) -> Any:
        epoch = secrets.token_hex(16)
        result = self._client.fence(epoch, timeout=self._timeout, check=check)
        with self._lock:
            self._epoch = epoch
        return result

    # -- the provider contract ---------------------------------------------------------------

    def ready(self, snapshot: AndroidSnapshot, evidence: AndroidInputEvidence, spec: AgentTaskSpec) -> tuple[bool, str]:
        """Pin the helper's boot and instrumentation run and require a quiet, healthy physical source."""
        del evidence, spec  # routing and scope were checked by the session; this proves the device side
        hello = self._client.hello(timeout=self._timeout, check=lambda: None)
        if hello.boot_id != snapshot.boot_id:
            return False, "Android helper runs on a different boot than the checked device"
        with self._lock:
            if self._helper is not None and self._helper != (hello.boot_id, hello.helper_epoch):
                raise AgentControlBusy("Android helper restarted; earlier commands are unknown")
            self._helper = (hello.boot_id, hello.helper_epoch)
            self._active = False
        return self._quiet()

    def _quiet(self) -> tuple[bool, str]:
        if not self._source.healthy:
            return False, "Android physical input source is not running"
        if self._source.idle_for() < self._idle:
            return False, "Android physical input was active within the idle window"
        return True, ""

    def checkpoint(self, binding: tuple[str, str, int]) -> None:
        """Refuse once physical input took over or the source stopped; this never sends input."""
        del binding
        with self._lock:
            active = self._active
        if active:
            raise AgentControlBusy("Android physical input took over")
        if not self._source.healthy:
            raise AgentTaskError("Android physical input source is not running")

    def lease(self, proposal: AndroidActionProposal, request_id: str) -> AndroidCommandLease:
        """Fence the device into a fresh epoch that only this request may run under."""
        self.checkpoint(("", "", 0))
        ready, reason = self._quiet()
        if not ready:
            raise AgentControlBusy(reason)
        fence = self._fence(lambda: None)
        if fence.inflight is not None or not fence.queue_empty:
            raise AgentTaskError("Android helper still has an earlier write in progress")
        epoch = fence.epoch
        device = device_identity("android", proposal.snapshot.physical_id)

        @contextmanager
        def device_fence() -> Iterator[None]:
            try:
                yield
            except BaseException:
                self._fence_quietly()  # stop whatever this lease queued before the error escapes
                raise

        def dispatch(name: str, arguments: dict[str, Any], deadline: float,
                     check: Callable[[], None]) -> AndroidActionResult:
            return self._dispatch(request_id, epoch, name, arguments, deadline, check)

        def settle(result: AndroidActionResult) -> dict[str, Any]:
            return self._settle(request_id, epoch, proposal.snapshot.boot_id, device, result)

        return AndroidCommandLease(proposal, request_id, epoch, device_fence, lambda: self.checkpoint(("", "", 0)),
                                   settle, dispatch=dispatch)

    # -- dispatch and settlement -------------------------------------------------------------

    def _dispatch(self, request_id: str, epoch: str, name: str, arguments: dict[str, Any],
                  deadline: float, check: Callable[[], None]) -> AndroidActionResult:
        command = helper_command(name, arguments)
        accepted, _reason = self._client.begin(request_id, epoch, command, timeout=self._timeout, check=check)
        if not accepted:
            return AndroidActionResult("pre_input_refused", 0)
        while True:
            check()
            settlement = self._client.settle(request_id, timeout=self._timeout, check=check)
            if settlement.status in _TERMINAL:
                return AndroidActionResult(_TERMINAL[settlement.status], 0)  # type: ignore[arg-type]
            if settlement.status == "rejected":
                raise AgentTaskError("Android helper lost a command it accepted")
            if self._clock() >= deadline:
                raise AgentTaskError("Android helper command did not settle before its deadline")
            time.sleep(_POLL)

    def _settle(self, request_id: str, epoch: str, boot_id: str, device: dict[str, str],
                result: AndroidActionResult) -> dict[str, Any]:
        value = self._client.settle(request_id, timeout=self._timeout, check=lambda: None)
        if result.phase == "pre_input_refused":
            # Never queued, so the ledger has no record: it answers "rejected" under its current epoch.
            settled = value.status == "rejected"
        else:
            settled = value.epoch == epoch and value.status in _TERMINAL
        if value.boot_id != boot_id or not settled:
            raise AgentTaskError("Android helper settlement does not match this command")
        return {"device": device, "epoch": epoch, "inputs_released": value.input_released,
                "queue_empty": value.queue_empty, "request_id": request_id, "boot_id": boot_id}

    def close(self) -> None:
        """Fence the device so nothing this provider began can still run, then stop the source."""
        try:
            self._fence_quietly()
        finally:
            self._source.close()
