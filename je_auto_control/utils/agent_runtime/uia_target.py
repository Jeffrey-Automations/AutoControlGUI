"""Expose scoped UI fixture observations under managed authority without granting actions."""
from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, ClassVar, Mapping, NoReturn

from .context import TaskOperation, authorization_key, current_operation
from .errors import AgentTaskError
from .models import AgentTaskSpec
from .observation_report import ObservationReport
from .scoped_uia import ScopedUiaSource, UiaField
from .semantic_target import SemanticSnapshot, SemanticTarget
from .uia_launch import BoundUiaWindow

_CAPTURE_CHECK_INTERVAL = 0.05

UIA_FIELDS = ("document_id", "duplicate", "empty", "enabled", "job_status", "password")
UIA_SELECTORS = (UiaField("document_id", "1001", "value"), UiaField("job_status", "1002", "value"),
                 UiaField("empty", "1003", "value"), UiaField("enabled", "1004", "enabled"),
                 UiaField("password", "1005", "value"), UiaField("duplicate", "1006", "value"))


def _native_automation() -> Any:
    # pylint: disable-next=import-outside-toplevel  # reason: acquire the optional backend lazily
    from ..accessibility.backends.windows_automation import (
        _create_automation, enter_apartment, import_comtypes_client,
    )
    try:
        client = import_comtypes_client()
        enter_apartment()
        return _create_automation(client.GetModule("UIAutomationCore.dll"))
    except (ImportError, OSError):
        raise AgentTaskError("native UI Automation is unavailable") from None


@dataclass(frozen=True)
class _Scope:
    spec: AgentTaskSpec
    owner: tuple[str, str, str | None] | None


class UiaObservationTarget(SemanticTarget):
    """A host factory owns acquisition and cleanup; task JSON supplies no window or selectors."""

    observation_sources: ClassVar[tuple[str, ...]] = ("uia",)
    observation_fields: ClassVar[tuple[str, ...]] = UIA_FIELDS

    def __init__(self, target_id: str, acquire: Callable[[Callable[[], None]], ScopedUiaSource],
                 close: Callable[[], None]) -> None:
        self._target_id, self._acquire, self._close = target_id, acquire, close
        self._source: ScopedUiaSource | None = None
        self._scope: _Scope | None = None
        self._terminal = threading.Event()
        self._work = threading.RLock()
        self._publication = threading.Lock()

    @classmethod
    def from_window_owner(cls, target_id: str,
                          acquire: Callable[[Callable[[], None]], BoundUiaWindow],
                          close: Callable[[], None]) -> UiaObservationTarget:
        """Create COM during managed readiness on the source's owning thread."""
        def source(checkpoint: Callable[[], None]) -> ScopedUiaSource:
            binding = acquire(checkpoint)
            binding.verify(checkpoint)
            automation = _native_automation()
            binding.verify(checkpoint)
            return ScopedUiaSource(binding, target_id, UIA_SELECTORS, automation)
        return cls(target_id, source, close)

    def _validate(self, operation: TaskOperation) -> None:
        if (self._terminal.is_set() or current_operation() is not operation
                or self._scope != _Scope(operation.spec, authorization_key(operation.owner))):
            raise AgentTaskError("UI observation is outside its original live managed scope")

    def _checkpoint(self, operation: TaskOperation) -> None:
        self._validate(operation)
        operation.checkpoint()
        self._validate(operation)

    def _capture_checkpoint(self, operation: TaskOperation) -> Callable[[], None]:
        """Check scope on every COM call and the full runtime checkpoint at most every interval.

        A capture makes thousands of read-only COM calls, and each full checkpoint is a
        durable budget write plus authority queries. Nothing is published until the
        unthrottled checkpoint that follows the capture, so a revocation during reads is
        still seen before publication, within one interval.
        """
        last = [float("-inf")]

        def check() -> None:
            self._validate(operation)
            if time.monotonic() - last[0] >= _CAPTURE_CHECK_INTERVAL:
                self._checkpoint(operation)
                last[0] = time.monotonic()
        return check

    def ready(self, spec: AgentTaskSpec) -> tuple[bool, str]:
        """Acquire only after pinning this managed task; retain cleanup after failed acquisition."""
        with self._work:
            operation = current_operation()
            if operation is None or operation.spec != spec or spec.target != self._target_id:
                raise AgentTaskError("UI observation requires its host-selected managed target")
            scope = _Scope(spec, authorization_key(operation.owner))
            if self._scope is not None and self._scope != scope:
                raise AgentTaskError("UI observation already belongs to another managed scope")
            self._scope = scope
            self._checkpoint(operation)
            if self._source is None:
                self._acquire_source(operation)
            return True, ""

    def _acquire_source(self, operation: TaskOperation) -> None:
        try:
            source = self._acquire(lambda: self._checkpoint(operation))
            self._checkpoint(operation)
            if source.field_scope != UIA_FIELDS or source.target_id != self._target_id:
                raise AgentTaskError("UI fixture source does not match its host field contract")
            with self._publication:
                self._validate(operation)
                self._source = source
        except BaseException as primary:  # reason: failed acquisition owners remain reachable for retry cleanup
            try:
                self.cleanup()
            except BaseException as cleanup:
                raise primary from cleanup
            raise

    def observe(self) -> dict[str, Any]:
        """Publish scoped best-effort and partial fields through the existing report path."""
        with self._work:
            operation = current_operation()
            if operation is None or self._source is None:
                raise AgentTaskError("UI observation has no managed source")
            self._checkpoint(operation)
            started = time.perf_counter()
            value = self._source.capture(self._capture_checkpoint(operation))
            self._checkpoint(operation)
            return ObservationReport("uia", (("uia", value),), started, time.perf_counter(), UIA_FIELDS).to_dict()

    def perform_grounded(self, name: str, arguments: Mapping[str, Any], *,
                         expected: SemanticSnapshot, operation_id: str) -> NoReturn:
        """UI observation grants no Invoke, SetValue, input or application command authority."""
        raise AgentTaskError("UI observation target is read-only")

    def cleanup(self) -> None:
        """Interrupt owned work without the capture lock; failed close remains retryable."""
        with self._publication:
            self._terminal.set()
        self._close()
