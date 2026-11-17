"""Retain pinned UI fixture resources before acquisition and through failed retirement."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PureWindowsPath
import secrets
import sys
from typing import Callable

from .capture_metadata import _identifier
from .errors import AgentTaskError
from .uia_launch import BoundUiaWindow, OwnedUiaLauncher
from .uia_target import UiaObservationTarget
from ..exception.control_signals import is_run_interruption
from ..executor.run_control import ExecutionStopped
from ..process_memory.windows_image import WindowsImageObserver
from ..process_memory.windows_launch import ImageLease, ImageObserver, PinnedExecutable, launch_attested
from ..process_memory.windows_window import WindowOwnerQuery


@dataclass(frozen=True)
class UiaFixtureImage:
    """Host-selected UI artifact and attestation bounds, never supplied by task JSON."""

    pin: PinnedExecutable
    path: str = field(repr=False)
    target_id: str
    max_image_bytes: int = 64 << 20
    attestation_timeout: float = 5.0

    def __post_init__(self) -> None:
        _identifier(self.target_id)
        if (not isinstance(self.pin, PinnedExecutable)
                or (self.pin.executable, self.pin.version) != ("uia-fixture", "1")):
            raise AgentTaskError("UI fixture requires its own executable identity")
        if (not isinstance(self.path, str) or not self.path or "\0" in self.path
                or len(self.path) >= 32768 or not PureWindowsPath(self.path).is_absolute()):
            raise AgentTaskError("UI fixture requires an absolute Windows image path")
        self._check_bounds()

    def _check_bounds(self) -> None:
        if type(self.max_image_bytes) is not int or not 0 < self.max_image_bytes <= 64 << 20:
            raise AgentTaskError("UI fixture image budget is invalid")
        if (type(self.attestation_timeout) not in (int, float)
                or not 0 < self.attestation_timeout <= 60):
            raise AgentTaskError("UI fixture attestation budget is invalid")


@dataclass(frozen=True)
class _UiaOwners:
    image: UiaFixtureImage
    launcher: OwnedUiaLauncher
    lease: ImageLease
    observer: ImageObserver

    def acquire(self, checkpoint: Callable[[], None]) -> BoundUiaWindow:
        """Attest the leased file before accepting the original child's correlated HWND."""
        checkpoint()
        image = self.image
        launch = launch_attested(image.pin, image.path, self.launcher,
            lease=self.lease, observer=self.observer, max_bytes=image.max_image_bytes,
            timeout=image.attestation_timeout, checkpoint=checkpoint)
        checkpoint()
        binding = self.launcher.bind_window(launch, checkpoint=checkpoint)
        checkpoint()
        return binding

    def close(self) -> None:
        """Attempt every owner after the managed target has revoked acquisition."""
        failures: list[BaseException] = []
        for close in (self.launcher.close, self.observer.close, self.lease.close):
            try:
                close()
            # pylint: disable-next=broad-exception-caught  # reason: attempt all owners before propagating interruption
            except BaseException as error:  # reason: collect every owner failure before raising
                failures.append(error)
        if failures:
            for failure in failures:
                if is_run_interruption(failure) or isinstance(failure, ExecutionStopped):
                    raise failure
            raise failures[0]


def owned_uia_target(image: UiaFixtureImage, *, launcher: OwnedUiaLauncher,
                     lease: ImageLease, observer: ImageObserver) -> UiaObservationTarget:
    """Bind complete ownership to managed readiness without acquiring a process or COM object."""
    if lease is observer:
        raise AgentTaskError("UI fixture requires independent image owners")
    owner = _UiaOwners(image, launcher, lease, observer)
    return UiaObservationTarget.from_window_owner(image.target_id, owner.acquire, owner.close)


def native_uia_target(image: UiaFixtureImage) -> UiaObservationTarget:
    """Construct inert native owners inside an owned helper; readiness performs acquisition."""
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise AgentTaskError("UI fixture requires 64-bit Windows")
    launcher = OwnedUiaLauncher(secrets.token_bytes(16), windows=WindowOwnerQuery())
    return owned_uia_target(image, launcher=launcher,
                            lease=WindowsImageObserver(), observer=WindowsImageObserver())
