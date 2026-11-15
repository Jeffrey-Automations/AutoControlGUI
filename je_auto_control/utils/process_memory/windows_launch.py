"""Attest a process this host launched itself, from an image file pinned by SHA-256.

The only identity this module mints is for a launch the host performed: the
image file is leased read-only (writers and deleters excluded) and digested
before the process starts, the digest must equal the host-configured pin, and
after the launch the process's own image is observed again and must be the
same leased file with the same digest. The resulting attestor names only that
process, by the PID and birth measured from the launch's own handle.

It proves which bytes were on disk while the image was mapped, not which code
is running now. A process the host did not launch cannot be attested here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hmac
import re
import time
from typing import Callable, NoReturn, Protocol

from je_auto_control.utils.exception.control_signals import raise_if_run_interrupted
from je_auto_control.utils.executor.run_control import ExecutionStopped

from .models import FailureReason, MemoryObservationError, ProcessIdentity, _identifier
from .windows_facts import NativeProcessFacts
from .windows_image import LeasedImageFile, ObservedImageFile

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _fail(reason: FailureReason) -> NoReturn:
    raise MemoryObservationError(reason)


@dataclass(frozen=True)
class PinnedExecutable:
    """Host configuration: the image bytes an identity names, and the labels it carries."""

    host: str = field(repr=False)
    session: str = field(repr=False)
    executable: str
    version: str
    sha256: str = field(repr=False)

    def __post_init__(self) -> None:
        for value in (self.host, self.session, self.executable, self.version):
            _identifier(value)
        if not isinstance(self.sha256, str) or not _SHA256.fullmatch(self.sha256):
            _fail(FailureReason.UNSUPPORTED)


@dataclass(frozen=True)
class LaunchRecord:
    """PID and birth measured from the process handle the launch itself returned."""

    pid: int = field(repr=False)
    birth: int = field(repr=False)


class ImageLease(Protocol):
    """The pre-launch half of :class:`~.windows_image.WindowsImageObserver`."""

    def lease(self, path: str, *, max_bytes: int, timeout: float,
              checkpoint: Callable[[], None]) -> LeasedImageFile: ...

    def close(self) -> None: ...


class ImageObserver(Protocol):
    """The post-launch half of :class:`~.windows_image.WindowsImageObserver`."""

    def observe(self, pid: int, *, max_bytes: int, timeout: float,
                checkpoint: Callable[[], None]) -> ObservedImageFile: ...

    def close(self) -> None: ...


#: Starts ``path`` and returns what it measured from the new process's own
#: handle. The caller's launcher owns the child: when attestation fails it is
#: the caller that ends it.
Launcher = Callable[[str], LaunchRecord]


class OwnedLaunchAttestor:
    """Attest the one launched process, and only while its facts are those attested."""

    def __init__(self, pin: PinnedExecutable, record: LaunchRecord, observed: ObservedImageFile) -> None:
        self._pin, self._record, self._observed = pin, record, observed

    def __call__(self, facts: NativeProcessFacts) -> ProcessIdentity:
        if (not isinstance(facts, NativeProcessFacts) or facts != self._observed.process
                or (facts.pid, facts.birth) != (self._record.pid, self._record.birth)):
            _fail(FailureReason.TARGET_CHANGED)
        pin = self._pin
        return ProcessIdentity(pin.host, pin.session, facts.pid, facts.birth, pin.executable,
                               pin.version, facts.architecture, facts.pointer_bits)


@dataclass
class OwnedLaunch:
    """An attested launch. Both file leases stay open until :meth:`close` succeeds."""

    identity: ProcessIdentity
    attestor: OwnedLaunchAttestor = field(repr=False)
    record: LaunchRecord = field(repr=False)
    _lease: ImageLease = field(repr=False)
    _observer: ImageObserver = field(repr=False)

    def close(self) -> None:
        """Close both leases; a failure leaves the rest to a later ``close``."""
        _close_all(self._observer, self._lease)


def _close_all(*owners: ImageLease | ImageObserver) -> None:
    failed = False
    for owner in owners:
        try:
            owner.close()
        except MemoryObservationError:
            failed = True
    if failed:
        _fail(FailureReason.CLEANUP_FAILED)


def _launch(launch: Launcher, path: str) -> LaunchRecord:
    try:
        record = launch(path)
    except MemoryObservationError:
        raise
    except Exception as error:  # reason: launcher detail (paths, arguments) must not reach the failure
        if isinstance(error, ExecutionStopped):
            raise
        raise_if_run_interrupted(error)
        _fail(FailureReason.UNSUPPORTED)
    if (not isinstance(record, LaunchRecord) or type(record.pid) is not int
            or type(record.birth) is not int or record.pid <= 0 or record.birth <= 0):
        _fail(FailureReason.TARGET_CHANGED)
    return record


def _same_file(leased: LeasedImageFile, observed: ObservedImageFile) -> bool:
    return ((observed.volume, observed.file_id, observed.size) == (leased.volume, leased.file_id, leased.size)
            and hmac.compare_digest(observed.sha256, leased.sha256))


def launch_attested(pin: PinnedExecutable, path: str, launch: Launcher, *,
                    lease: ImageLease, observer: ImageObserver, max_bytes: int, timeout: float,
                    checkpoint: Callable[[], None], clock: Callable[[], float] = time.monotonic) -> OwnedLaunch:
    """Lease and digest ``path``, check the pin, launch, then confirm the child runs that file.

    ``lease`` and ``observer`` are two fresh image observers; one deadline
    covers both measurements. On any failure both are closed (a failed close
    still surfaces as the original error), and the launched child, if any, is
    left to the caller's launcher.
    """
    if not isinstance(pin, PinnedExecutable):
        _fail(FailureReason.UNSUPPORTED)
    deadline = clock() + timeout
    try:
        leased = lease.lease(path, max_bytes=max_bytes, timeout=timeout, checkpoint=checkpoint)
        if not hmac.compare_digest(leased.sha256, pin.sha256):
            _fail(FailureReason.UNSUPPORTED)
        checkpoint()
        record = _launch(launch, path)
        remaining = deadline - clock()
        if remaining <= 0:
            _fail(FailureReason.DEADLINE_EXCEEDED)
        observed = observer.observe(record.pid, max_bytes=max_bytes, timeout=remaining, checkpoint=checkpoint)
        if not _same_file(leased, observed):
            _fail(FailureReason.TARGET_CHANGED)
        attestor = OwnedLaunchAttestor(pin, record, observed)
        identity = attestor(observed.process)
    except BaseException:
        try:
            _close_all(observer, lease)
        except MemoryObservationError:
            pass
        raise
    return OwnedLaunch(identity, attestor, record, lease, observer)


__all__ = ["ImageLease", "ImageObserver", "LaunchRecord", "Launcher", "OwnedLaunch",
           "OwnedLaunchAttestor", "PinnedExecutable", "launch_attested"]
