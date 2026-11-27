"""Discover every ``AC_*`` action command exposed by the executor.

We can't simply hard-code the list because the executor's dispatch
table grows every release. Instead, we introspect ``action_executor``
at runtime (the LSP server is short-lived per session, so the cost
is paid once at startup).

The command set is the executor's own :meth:`known_commands`: the
``event_dict`` callables *and* the flow-control block commands
(``AC_sleep``, ``AC_loop``, ``AC_if_var`` ...) registered apart from it.
Reading ``event_dict`` alone reported every block command as unknown.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional


_DISCOVERY_CACHE: Optional[Dict[str, Optional[str]]] = None
_BLOCK_CACHE: Optional[FrozenSet[str]] = None


def _load_executor() -> Optional[Any]:
    try:
        from je_auto_control.utils.executor.action_executor import executor
    except ImportError:
        return None
    return executor


def _block_handlers() -> Mapping[str, Callable[..., Any]]:
    try:
        from je_auto_control.utils.executor.flow_control import BLOCK_COMMANDS
    except ImportError:
        return {}
    return BLOCK_COMMANDS


def _doc_of(callable_obj: Any) -> Optional[str]:
    doc = getattr(callable_obj, "__doc__", None)
    return doc.strip() if isinstance(doc, str) else None


def discover_actions() -> Dict[str, Optional[str]]:
    """Return ``{command_name: docstring_or_None}`` for every AC_* command.

    Cached after the first call. Reset by passing ``None`` to
    :func:`_reset_cache` (testing only).
    """
    global _DISCOVERY_CACHE
    if _DISCOVERY_CACHE is not None:
        return _DISCOVERY_CACHE
    executor = _load_executor()
    if executor is None:
        _DISCOVERY_CACHE = {}
        return _DISCOVERY_CACHE
    blocks = _block_handlers()
    out: Dict[str, Optional[str]] = {}
    for name in executor.known_commands():
        if not isinstance(name, str) or not name.startswith("AC_"):
            continue
        # The executor dispatches a block command before event_dict.
        handler = blocks.get(name, executor.event_dict.get(name))
        out[name] = _doc_of(handler)
    _DISCOVERY_CACHE = dict(sorted(out.items()))
    return _DISCOVERY_CACHE


def block_command_names() -> FrozenSet[str]:
    """Commands the executor runs as flow blocks; they take only an object."""
    global _BLOCK_CACHE
    if _BLOCK_CACHE is None:
        _BLOCK_CACHE = frozenset(_block_handlers())
    return _BLOCK_CACHE


def known_action_names() -> List[str]:
    """Sorted list of every ``AC_*`` command name the executor exposes."""
    return list(discover_actions().keys())


def get_action_doc(name: str) -> Optional[str]:
    """Return the docstring for one command, or None when unknown."""
    return discover_actions().get(name)


def _reset_cache() -> None:
    """Test-only: forget the cached discovery so the next call re-imports."""
    global _DISCOVERY_CACHE, _BLOCK_CACHE
    _DISCOVERY_CACHE = None
    _BLOCK_CACHE = None


__all__ = [
    "block_command_names", "discover_actions", "known_action_names",
    "get_action_doc",
]
