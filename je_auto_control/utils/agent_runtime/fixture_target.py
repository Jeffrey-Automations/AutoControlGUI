"""Own pinned fixture startup, guarded semantic reads and retryable resource retirement."""
from __future__ import annotations

from _thread import LockType
from dataclasses import dataclass, field, replace
from enum import Enum, auto
import math
import threading
from typing import Any, Callable, Mapping, NoReturn

from .errors import AgentTaskError
from .context import TaskOperation, current_operation
from .fixture_commands import FIXTURE_COMMAND, FixtureCommands
from .fixture_launch import OwnedChannelLauncher
from .memory_target import MemoryBinding, MemorySemanticTarget, _owner_key
from .models import AgentTaskSpec
from .semantic_target import SemanticReceipt, SemanticSnapshot, SemanticTarget
from ..exception.control_signals import is_run_interruption
from ..executor.run_control import ExecutionStopped
from ..process_memory.image_guard import guard_probe_image
from ..process_memory.models import FailureReason, MemoryObservationError, ProcessProvider
from ..process_memory.pe_image import plan_pinned_image
from ..process_memory.reader import ProcessMemoryReader
from ..process_memory.windows_launch import (
    ImageLease, ImageObserver, OwnedLaunchAttestor, PinnedExecutable, launch_attested,
)


@dataclass(frozen=True)
class FixtureImage:
    """Trusted host input, never accepted from a task or bootstrap packet."""

    pin: PinnedExecutable
    path: str = field(repr=False)
    baseline: bytes = field(repr=False)
    challenge: bytes = field(repr=False)
    target_id: str
    read_timeout: float = 1.0


@dataclass(frozen=True)
class _Owners:
    launcher: OwnedChannelLauncher
    lease: ImageLease
    observer: ImageObserver


class _State(Enum):
    NEW = auto()
    STARTING = auto()
    ACTIVE = auto()
    RETIRED = auto()


@dataclass(frozen=True)
class _ManagedScope:
    spec: AgentTaskSpec
    owner: tuple[str, str, str | None] | None


@dataclass
class _Lifecycle:
    state: _State = _State.NEW
    scope: _ManagedScope | None = field(default=None, repr=False)
    ready: LockType = field(default_factory=threading.Lock, repr=False)


def _raise_failure(failures: list[BaseException]) -> NoReturn:
    for error in failures:
        if (not isinstance(error, Exception) or isinstance(error, ExecutionStopped)
                or is_run_interruption(error)):
            raise error
    raise failures[0]


class OwnedFixtureTarget(SemanticTarget):
    """Internal assembly; construct before startup so failed cleanup remains reachable."""

    def __init__(self, image: FixtureImage, *, launcher: OwnedChannelLauncher,
                 lease: ImageLease, observer: ImageObserver,
                 provider_factory: Callable[[OwnedLaunchAttestor], ProcessProvider]) -> None:
        self._image = image
        self._owners = _Owners(launcher, lease, observer)
        self._provider_factory = provider_factory
        self._target: MemorySemanticTarget | None = None
        self._reader: ProcessMemoryReader | None = None
        self._lifecycle = _Lifecycle()
        self._publication = threading.Lock()

    def _live(self) -> None:
        if self._lifecycle.state is _State.RETIRED:
            raise AgentTaskError("fixture target is retired")

    def start(self, *, checkpoint: Callable[[], None]) -> OwnedFixtureTarget:
        """Acquire once; a failed start retires use but leaves every owner available."""
        with self._publication:
            self._live()
            if self._lifecycle.state is not _State.NEW:
                raise AgentTaskError("fixture target cannot be started twice")
            self._lifecycle.state = _State.STARTING

        def check() -> None:
            self._live()
            checkpoint()
            self._live()

        try:
            target = self._assemble(check)
            check()
            with self._publication:
                self._live()
                self._target = target
                self._lifecycle.state = _State.ACTIVE
        except BaseException as error:
            try:
                self.cleanup()
            # pylint: disable-next=broad-exception-caught  # reason: preserve startup or cleanup interruption identity
            except BaseException as cleanup:
                _raise_failure([error, cleanup])
            raise
        return self

    def _assemble(self, check: Callable[[], None]) -> MemorySemanticTarget:
        image = self._image
        check()
        if (not isinstance(image.challenge, bytes) or len(image.challenge) != 16
                or not any(image.challenge)):
            raise MemoryObservationError(FailureReason.UNSUPPORTED)
        if (type(image.read_timeout) not in (int, float)
                or not math.isfinite(image.read_timeout) or not 0 < image.read_timeout <= 60):
            raise MemoryObservationError(FailureReason.UNSUPPORTED)
        plan = plan_pinned_image(image.baseline, image.pin)
        if image.pin.version != "1" or plan.checked_bytes + 72 > 1 << 20:
            raise MemoryObservationError(FailureReason.UNSUPPORTED)
        owners = self._owners
        launch = launch_attested(image.pin, image.path, owners.launcher, lease=owners.lease,
                                 observer=owners.observer, max_bytes=len(image.baseline),
                                 timeout=1.0, checkpoint=check)
        check()
        control = owners.launcher.bind_control(launch, image.challenge, checkpoint=check)
        session = control.bootstrap(timeout=1.0, checkpoint=check)
        probe = replace(session.binding.probe(image.pin.executable),
                        max_bytes=plan.checked_bytes + 72, max_regions=1024,
                        timeout=image.read_timeout)
        probe = guard_probe_image(probe, plan, image_sha256=launch.image_sha256)
        binding = MemoryBinding(image.target_id, launch.identity, probe, probe.fields)
        check()
        self._reader = ProcessMemoryReader(self._provider_factory(launch.attestor))
        check()
        return MemorySemanticTarget(binding, self._reader,
                                    FixtureCommands(binding, session.launch_nonce, control))

    def _active(self) -> MemorySemanticTarget:
        self._live()
        target = self._target
        if target is None:
            raise AgentTaskError("fixture target has not completed startup")
        return target

    def ready(self, spec: AgentTaskSpec) -> tuple[bool, str]:
        """Claim managed ownership before acquiring any fixture resources."""
        # pylint: disable-next=consider-using-with  # reason: concurrent readiness must refuse instead of blocking
        if not self._lifecycle.ready.acquire(blocking=False):
            raise AgentTaskError("fixture readiness is already in progress")
        try:
            operation = self._claim_scope(spec)
            return self._ready_owned(spec, operation)
        finally:
            self._lifecycle.ready.release()

    def _claim_scope(self, spec: AgentTaskSpec) -> TaskOperation:
        operation = current_operation()
        if (operation is None or operation.spec != spec or spec.target != self._image.target_id
                or set(spec.allowed_tools) != {FIXTURE_COMMAND}):
            raise AgentTaskError("fixture startup requires its exact managed task scope")
        operation.checkpoint()
        scope = _ManagedScope(spec, _owner_key(operation.owner))
        with self._publication:
            self._live()
            if self._lifecycle.state is _State.STARTING:
                raise AgentTaskError("fixture startup is already in progress")
            if self._lifecycle.scope is not None and self._lifecycle.scope != scope:
                raise AgentTaskError("fixture belongs to a different managed owner or task")
            self._lifecycle.scope = scope
        return operation

    def _ready_owned(self, spec: AgentTaskSpec, operation: TaskOperation) -> tuple[bool, str]:
        def check() -> None:
            if current_operation() is not operation:
                raise AgentTaskError("fixture startup operation scope changed")
            operation.checkpoint()
            if current_operation() is not operation:
                raise AgentTaskError("fixture startup operation scope changed")
            self._live()

        try:
            if self._lifecycle.state is _State.NEW:
                self.start(checkpoint=check)
            check()
            result = self._active().ready(spec)
            check()
            return result
        except BaseException as error:
            try:
                self.cleanup()
            # pylint: disable-next=broad-exception-caught  # reason: preserve readiness or cleanup interruption identity
            except BaseException as cleanup:
                _raise_failure([error, cleanup])
            raise

    def observe(self) -> dict[str, Any]:
        """Expose only the reviewed semantic fields through the original runtime scope."""
        result = self._active().observe()
        self._live()
        return result

    def perform_grounded(self, name: str, arguments: Mapping[str, Any], *,
                         expected: SemanticSnapshot, operation_id: str) -> SemanticReceipt:
        """Keep original grounding, command policy and unknown-effect handling."""
        result = self._active().perform_grounded(
            name, arguments, expected=expected, operation_id=operation_id)
        self._live()
        return result

    def perform(self, _name: str, _arguments: Mapping[str, Any]) -> None:
        """Refuse calls that omit the original semantic observation."""
        raise AgentTaskError("fixture commands require grounded dispatch")

    def cleanup(self) -> None:
        """Retire IPC first; try every resource and retain failed owners for retry."""
        with self._publication:
            self._lifecycle.state = _State.RETIRED
        actions = [self._owners.launcher.close]
        if self._target is not None:
            actions.append(self._target.cleanup)
        if self._reader is not None:
            actions.append(self._close_reader)
        actions.extend((self._owners.observer.close, self._owners.lease.close))
        failures: list[BaseException] = []
        for action in actions:
            try:
                action()
            # pylint: disable-next=broad-exception-caught  # reason: retire all owners before preserving interruption
            except BaseException as error:
                failures.append(error)
        if failures:
            _raise_failure(failures)

    def _close_reader(self) -> None:
        if self._reader is not None and not self._reader.close_pending():
            raise MemoryObservationError(FailureReason.CLEANUP_FAILED)
