"""Start and stop the machine's remote-desktop host on a worker thread.

Stopping a host joins its threads (up to 2 s), and starting one stops the
host already running first, so both used to hold the GUI thread for that
long. The Host panel and the Quick Connect screen hand these to a
:class:`~je_auto_control.gui._slow_op.SlowOp` instead.
"""
from typing import Any, Callable

from je_auto_control.utils.remote_desktop.registry import SLOT_HOST, registry


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


def stop_host(owner: str) -> bool:
    """Worker thread: stop the machine's host, whoever started it."""
    return registry.evict(SLOT_HOST, by=owner)


def release_host(owner: str, _host: Any) -> None:
    """A host that came up for a panel that is gone: nobody is left to stop it."""
    registry.release(SLOT_HOST, owner)


__all__ = ["release_host", "replace_host", "stop_host"]
