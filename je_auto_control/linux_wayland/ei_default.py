"""Default owned EI sender cache; failed retirement retains its owner."""
from typing import Optional
import threading

from je_auto_control.linux_wayland._input_state import InputFailure, blocked_input
from je_auto_control.linux_wayland.ei_protocol import InputBackend
from je_auto_control.linux_wayland.ei_transport import EiWorkerClient
from je_auto_control.utils.exception.control_signals import raise_caused_run_interruption


def _new_default_backend() -> InputBackend:
    return EiWorkerClient()


_DEFAULT_BACKEND: Optional[InputBackend] = None
_PROBE_FAILED = False
_NEEDS_CONNECT = False
_BLOCKED_PROBE: Optional[InputFailure] = None
_DEFAULT_LOCK = threading.Lock()


def _retire_after_failure(backend: InputBackend, error: BaseException) -> None:
    from je_auto_control.linux_wayland.libei import LibeiUnavailable
    global _BLOCKED_PROBE
    try:
        backend.disconnect()
    except BaseException as cleanup_error:  # reason: retain owner and preserve original controls
        _BLOCKED_PROBE = InputFailure('failed', 'libei', 'EI helper retirement failed', fallback_allowed=False)
        raise_caused_run_interruption(error)
        raise_caused_run_interruption(cleanup_error)
        if not isinstance(cleanup_error, Exception):
            raise
        raise LibeiUnavailable('EI helper retirement failed', state='failed') from cleanup_error


def connected_backend() -> Optional[InputBackend]:
    """Return a connected backend, or None — probing at most once.

    The probe involves a portal round trip and a consent dialog, so a host
    where libei cannot be used must pay for that discovery once rather than
    on every keystroke. Only optional absence returns None. Authority/protocol
    refusals retain inert metadata and raise until an explicit reset/retry.
    """
    from je_auto_control.linux_wayland.libei import LibeiUnavailable
    global _DEFAULT_BACKEND, _PROBE_FAILED, _BLOCKED_PROBE, _NEEDS_CONNECT
    with _DEFAULT_LOCK:
        if _BLOCKED_PROBE is not None:
            raise LibeiUnavailable(_BLOCKED_PROBE.message, state=_BLOCKED_PROBE.state,
                                   fallback_allowed=_BLOCKED_PROBE.fallback_allowed)
        if _PROBE_FAILED:
            return None
        if _DEFAULT_BACKEND is None:
            _DEFAULT_BACKEND = _new_default_backend()
            _NEEDS_CONNECT = True
        backend = _DEFAULT_BACKEND
        try:
            if not backend.is_available:
                backend.disconnect()
                _DEFAULT_BACKEND = None
                _PROBE_FAILED = True
                return None
            if _NEEDS_CONNECT:
                backend.connect()
                _NEEDS_CONNECT = False
        except BaseException as error:  # reason: retire cancellation without losing ownership
            _retire_after_failure(backend, error)
            _DEFAULT_BACKEND = None
            blocked = blocked_input(error)
            _PROBE_FAILED = True
            if blocked is not None:
                _BLOCKED_PROBE = blocked[1]
                raise blocked[0]
            if not isinstance(error, (LibeiUnavailable, OSError, ValueError, AttributeError)):
                raise
            return None
        return backend


def _observed_input_state() -> tuple[Optional[str], bool]:
    """Inert snapshot for passive diagnostics; never construct a backend or wait on the portal-probe lock."""
    failure = _BLOCKED_PROBE
    if failure is not None:
        return failure.state, failure.fallback_allowed
    backend = _DEFAULT_BACKEND
    if backend is None:
        return ('unavailable', True) if _PROBE_FAILED else (None, False)
    return backend.observed_state(), False


def get_default_backend() -> Optional[InputBackend]:
    """Return a cached helper without requesting portal consent."""
    from je_auto_control.linux_wayland.libei import LibeiUnavailable
    global _DEFAULT_BACKEND, _NEEDS_CONNECT, _PROBE_FAILED
    with _DEFAULT_LOCK:
        if _BLOCKED_PROBE is not None:
            raise LibeiUnavailable(_BLOCKED_PROBE.message, state=_BLOCKED_PROBE.state,
                                   fallback_allowed=_BLOCKED_PROBE.fallback_allowed)
        if _PROBE_FAILED:
            return None
        if _DEFAULT_BACKEND is None:
            _DEFAULT_BACKEND = _new_default_backend()
            _NEEDS_CONNECT = True
        backend = _DEFAULT_BACKEND
        if backend.is_available:
            return backend
        backend.disconnect()
        _DEFAULT_BACKEND = None
        _PROBE_FAILED = True
        return None


def reset_default_backend() -> None:
    """Explicitly retire the cached sender/refusal so a later request may seek a fresh grant."""
    global _DEFAULT_BACKEND, _PROBE_FAILED, _BLOCKED_PROBE, _NEEDS_CONNECT
    with _DEFAULT_LOCK:
        if _DEFAULT_BACKEND is not None:
            _DEFAULT_BACKEND.disconnect()
        _DEFAULT_BACKEND = None
        _PROBE_FAILED = False
        _NEEDS_CONNECT = False
        _BLOCKED_PROBE = None
