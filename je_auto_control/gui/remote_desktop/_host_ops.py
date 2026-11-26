"""Start and stop the machine's remote-desktop host on a worker thread.

Stopping a host joins its threads (up to 2 s), and starting one stops the
host already running first, so both used to hold the GUI thread for that
long. The Host panel and the Quick Connect screen hand these to a
:class:`~je_auto_control.gui._slow_op.SlowOp` instead. A TLS host's
certificate chain is read there too, before anything is stopped.
"""
import functools
import ssl
from typing import Any, Callable

from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.remote_desktop.registry import SLOT_HOST, registry


class HostTlsError(AutoControlException, ValueError):
    """A new host's certificate or key could not be loaded; the host already running was left alone."""


def replace_host(owner: str, build: Callable[[], Any],
                 on_displaced: Callable[[str, str], None]) -> Any:
    """Worker thread: stop the running host, start the new one and register it for ``owner``.

    In this order because the old host has to let go of its port before the
    new one binds it; the stop joins the old host's threads (2 s).
    """
    # Whoever started the running host is told it was replaced. Viewers
    # are left alone: they belong to other panels or to a script.
    registry.evict(SLOT_HOST, by=owner)
    host = build()
    host.start()
    registry.adopt(SLOT_HOST, host, owner, on_displaced)
    return host


def server_tls_context(cert_path: str, key_path: str) -> ssl.SSLContext:
    """Worker thread: a TLS 1.2+ server context holding the certificate chain; :class:`HostTlsError` when it fails."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    except (OSError, ValueError) as error:          # ssl.SSLError is an OSError
        raise HostTlsError(str(error)) from error
    return ctx


def replace_tls_host(owner: str, cert_path: str, key_path: str, build: Callable[..., Any],
                     on_displaced: Callable[[str, str], None]) -> Any:
    """Worker thread: load the certificate chain, then :func:`replace_host` with it as ``build``'s ``ssl_context``.

    The chain is read first, so a certificate that does not load stops nothing.
    """
    ssl_context = server_tls_context(cert_path, key_path)
    return replace_host(owner, functools.partial(build, ssl_context=ssl_context), on_displaced)


def stop_host(owner: str) -> bool:
    """Worker thread: stop the machine's host, whoever started it."""
    return registry.evict(SLOT_HOST, by=owner)


def release_host(owner: str, _host: Any) -> None:
    """A host that came up for a panel that is gone: nobody is left to stop it."""
    registry.release(SLOT_HOST, owner)


__all__ = ["HostTlsError", "release_host", "replace_host", "replace_tls_host", "server_tls_context", "stop_host"]
