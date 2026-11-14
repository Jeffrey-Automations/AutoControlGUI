"""mDNS / Zeroconf LAN discovery for AutoControl hosts.

Hosts call :class:`HostAdvertiser` to broadcast their presence on the
local network; viewers call :class:`HostBrowser` to discover them. Service
type is ``_autocontrol._tcp.local.``. Each advertised service carries
TXT properties: ``host_id``, ``signaling_url`` (optional). The viewer GUI
turns each discovered service into a one-click connect entry.

Both classes are fail-soft: if zeroconf isn't installed (the ``discovery``
extra) they raise on construction with a clear message — the GUI checks
:func:`is_discovery_available` before instantiating.
"""
from __future__ import annotations

import socket
import threading
from typing import Callable, Dict, List, Optional

from je_auto_control.utils.exception.control_signals import raise_caused_run_interruption
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.remote_desktop.media_retirement import (
    Completion, MediaRetirementError, RetirementStatus, require_retired, preserve_interrupted_owner,
)

try:
    from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf
    _AVAILABLE = True
except ImportError:  # pragma: no cover - optional dep
    Zeroconf = None  # type: ignore[assignment]
    ServiceBrowser = None  # type: ignore[assignment]
    ServiceInfo = None  # type: ignore[assignment]
    ServiceListener = None  # type: ignore[assignment]
    _AVAILABLE = False


_SERVICE_TYPE = "_autocontrol._tcp.local."


def is_discovery_available() -> bool:
    return _AVAILABLE


def _local_ip() -> str:
    """Best-effort: ask the kernel which interface routes to a public IP."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Connect-to-public-IP trick to discover the local interface
            # the kernel would pick for outbound traffic; UDP, so no
            # packet is sent and 8.8.8.8 (Google DNS) just stands in for
            # "any reachable public IP". The literal is the well-known
            # anycast probe address — parameterising it would obscure
            # intent — see the next line for the suppression marker.
            sock.connect(("8.8.8.8", 80))  # nosec B113  # NOSONAR — literal is the well-known Google DNS anycast address used as a routing probe target
            return sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        return "127.0.0.1"


class HostAdvertiser:
    """Broadcast a single host on the LAN; cancel via :meth:`stop`."""

    def __init__(self, *, host_id: str, port: int = 0,
                 signaling_url: Optional[str] = None,
                 server_name: Optional[str] = None) -> None:
        if not _AVAILABLE:
            raise ImportError(
                "LAN discovery needs the 'discovery' extra: "
                "pip install je_auto_control[discovery]"
            )
        self._host_id = host_id
        self._retire_lock = threading.Lock()
        self._unregister = Completion.PENDING
        self._release = Completion.PENDING
        self._stopping = False
        self._info = None
        self._zc = Zeroconf()
        try:
            ip = self._register(host_id, port, signaling_url, server_name)
        except BaseException as error:
            try:
                self.stop()
            except BaseException as cleanup_error:
                preserve_interrupted_owner(self, error, cleanup_error)
                raise cleanup_error from error
            raise
        autocontrol_logger.info(
            "lan discovery: advertised host_id=%s on %s", host_id, ip,
        )

    def _register(self, host_id: str, port: int, signaling_url: Optional[str],
                  server_name: Optional[str]) -> str:
        ip = _local_ip()
        props = {b"host_id": host_id.encode("utf-8")}
        if signaling_url:
            props[b"signaling_url"] = signaling_url.encode("utf-8")
        name = server_name or socket.gethostname()
        self._info = ServiceInfo(
            _SERVICE_TYPE,
            f"{name}-{host_id}.{_SERVICE_TYPE}",
            addresses=[socket.inet_aton(ip)],
            port=int(port) or 0,
            properties=props,
            server=f"{name}.local.",
        )
        self._zc.register_service(self._info)
        return ip

    @property
    def retirement_status(self) -> RetirementStatus:
        with self._retire_lock:
            failed: tuple[str, ...] = ()
            if self._unregister is Completion.UNCERTAIN:
                failed += ("advertiser.unregister",)
            if self._release is not Completion.CONFIRMED:
                failed += ("advertiser.close",)
            return RetirementStatus(self._stopping, self._release,
                                    self._unregister,
                                    self._stopping and self._release is not Completion.CONFIRMED,
                                    failed)

    def stop(self) -> None:
        """Retain a failed close; a failed goodbye remains uncertain."""
        failures = []
        with self._retire_lock:
            self._stopping = True
            if self._unregister is Completion.PENDING:
                self._unregister = Completion.UNCERTAIN
                try:
                    if self._info is not None:
                        self._zc.unregister_service(self._info)
                except BaseException as error:  # reason: finish close and then preserve any control signal
                    failures.append(error)
                else:
                    self._unregister = Completion.CONFIRMED
            if self._release is not Completion.CONFIRMED:
                try:
                    self._zc.close()
                except BaseException as error:  # reason: finish close and then preserve any control signal
                    failures.append(error)
                    self._release = Completion.UNCERTAIN
                else:
                    self._release = Completion.CONFIRMED
        for failure in failures:
            raise_caused_run_interruption(failure)
        require_retired(self)


class _BrowseListener:
    """Adapter that pumps zeroconf events into the user callback."""

    def __init__(self, on_change: Callable[[Dict[str, dict]], None]) -> None:
        self._on_change: Optional[Callable[[Dict[str, dict]], None]] = on_change
        self._services: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._publishing = 0

    def retire(self) -> None:
        """Close publication admission and release the callback without waiting for it."""
        with self._lock:
            self._on_change = None
            self._services.clear()

    @property
    def idle(self) -> bool:
        with self._lock:
            return self._publishing == 0

    def _publish(self, snapshot: Dict[str, dict]) -> None:
        with self._lock:
            callback = self._on_change
            if callback is None:
                return
            self._publishing += 1
        try:
            callback(snapshot)
        finally:
            with self._lock:
                self._publishing -= 1

    def add_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
        with self._lock:
            if self._on_change is None:
                return
        info = zc.get_service_info(type_, name, timeout=2000)
        if info is None:
            return
        record = self._service_record(info, name)
        with self._lock:
            if self._on_change is None:
                return
            self._services[name] = record
            snapshot = dict(self._services)
        self._publish(snapshot)

    @staticmethod
    def _service_record(info: "ServiceInfo", name: str) -> dict:
        props = info.properties or {}
        host_id = (props.get(b"host_id") or b"").decode(
            "utf-8", errors="replace",
        )
        signaling_url = (props.get(b"signaling_url") or b"").decode(
            "utf-8", errors="replace",
        )
        addresses = [socket.inet_ntoa(a) for a in (info.addresses or [])]
        return {
                "name": name,
                "host_id": host_id,
                "signaling_url": signaling_url,
                "ip": addresses[0] if addresses else "",
                "port": info.port or 0,
        }

    def remove_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
        # zc / type_ are positional callback parameters required by the
        # Zeroconf ServiceListener interface; we only need ``name`` here.
        del zc, type_  # suppress S1172 about the unused signature args
        with self._lock:
            if self._on_change is None:
                return
            self._services.pop(name, None)
            snapshot = dict(self._services)
        self._publish(snapshot)

    def update_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
        # Re-fetch and treat as add (replaces old entry under same name)
        self.add_service(zc, type_, name)


class HostBrowser:
    """Watch the LAN for AutoControl hosts.

    ``on_change(services_by_name: dict)`` fires on every add/remove/update.
    Cancel via :meth:`stop`.
    """

    def __init__(self, on_change: Callable[[Dict[str, dict]], None]) -> None:
        if not _AVAILABLE:
            raise ImportError(
                "LAN discovery needs the 'discovery' extra: "
                "pip install je_auto_control[discovery]"
            )
        self._state_lock = threading.Lock()
        self._retire_lock = threading.Lock()
        self._stopping = False
        self._cancel_attempted = False
        self._browser_done = False
        self._acquisition_uncertain = False
        self._release = Completion.PENDING
        self._failures: set[str] = set()
        self._browser: Optional[ServiceBrowser] = None
        self._listener = _BrowseListener(on_change)
        self._zc: Optional[Zeroconf] = None
        try:
            self._zc = Zeroconf()
            self._browser = ServiceBrowser(
                self._zc, _SERVICE_TYPE, listener=self._listener,
            )
        except BaseException as error:  # reason: retain partial acquisition before preserving constructor interruption
            self._acquisition_uncertain = True
            self._failures.add("browser.acquire")
            try:
                self.stop()
            except BaseException as cleanup_error:  # reason: retain ownership and preserve the original control signal
                preserve_interrupted_owner(self, error, cleanup_error)
                raise MediaRetirementError(self) from error
            raise

    @property
    def retirement_status(self) -> RetirementStatus:
        idle = self._listener.idle
        with self._state_lock:
            finalized = Completion.CONFIRMED if self._browser_done and idle else Completion.PENDING
            if self._acquisition_uncertain:
                finalized = Completion.UNCERTAIN
            resources = self._release if finalized is Completion.CONFIRMED else finalized
            complete = resources is Completion.CONFIRMED and finalized is Completion.CONFIRMED
            retryable = self._stopping and not complete and (
                (self._zc is not None and self._release is not Completion.CONFIRMED)
                or not self._acquisition_uncertain)
            return RetirementStatus(self._stopping, resources, finalized, retryable,
                                    tuple(sorted(self._failures)))

    def close_admission(self) -> None:
        """Report no further hosts, at once; :meth:`stop` still cancels the browser and closes zeroconf.

        Takes only short state locks and makes no native call.
        """
        self._listener.retire()
        with self._state_lock:
            self._stopping = True

    def stop(self) -> None:
        """Close publication, attempt cancellation once and observe original resource completion."""
        self._listener.retire()
        with self._state_lock:
            self._stopping = True
        if not self._retire_lock.acquire(blocking=False):
            require_retired(self)
            return
        failures: list[BaseException] = []
        try:
            if self._listener.idle:
                self._cancel_browser(failures)
                self._close_zeroconf(failures)
                self._observe_browser(failures)
        finally:
            self._retire_lock.release()
        preserve_interrupted_owner(self, *failures)
        require_retired(self)

    def _cancel_browser(self, failures: list[BaseException]) -> None:
        with self._state_lock:
            if self._cancel_attempted or self._browser is None:
                return
            self._cancel_attempted = True
        try:
            self._browser.cancel()
        except BaseException as error:  # reason: close Zeroconf independently before preserving interruption
            failures.append(error)
            with self._state_lock:
                self._failures.add("browser.cancel")

    def _close_zeroconf(self, failures: list[BaseException]) -> None:
        zc = self._zc
        if zc is None:
            return
        with self._state_lock:
            if self._release is Completion.CONFIRMED:
                return
        try:
            zc.close()
        except BaseException as error:  # reason: retain the documented retryable close before preserving interruption
            failures.append(error)
            with self._state_lock:
                self._release = Completion.UNCERTAIN
                self._failures.add("browser.close")
        else:
            with self._state_lock:
                self._release = Completion.CONFIRMED
                self._failures.discard("browser.close")

    def _observe_browser(self, failures: list[BaseException]) -> None:
        if self._browser is None:
            return
        try:
            finished = not self._browser.is_alive()
        except BaseException as error:  # reason: failed observation cannot acknowledge thread completion
            failures.append(error)
            with self._state_lock:
                self._failures.add("browser.observe")
            return
        with self._state_lock:
            self._browser_done = finished
            self._failures.discard("browser.observe")


def list_local_services(timeout_s: float = 2.0) -> List[dict]:
    """One-shot synchronous browse (collects whatever shows up in ``timeout``)."""
    if not _AVAILABLE:
        return []
    snapshot: Dict[str, dict] = {}
    done = threading.Event()
    def _on(services: Dict[str, dict]) -> None:
        snapshot.clear()
        snapshot.update(services)
    browser = HostBrowser(on_change=_on)
    try:
        done.wait(timeout=timeout_s)
    except BaseException as error:  # reason: preserve interruption while retaining incomplete browser cleanup
        try:
            browser.stop()
        except BaseException as cleanup_error:  # reason: attach ownership before preserving the original control signal
            preserve_interrupted_owner(browser, error, cleanup_error)
            raise
        raise
    else:
        browser.stop()
    return list(snapshot.values())


__all__ = [
    "HostAdvertiser", "HostBrowser",
    "is_discovery_available", "list_local_services",
]
