"""``AC_resolve_ref`` / ``AC_resolve_refs``: return referenced values, never log them in plaintext.

``secret://`` is refused outright: its values never enter an executor record
or an MCP result. An ``env://`` value often is a credential too, and it was
returned into the recorded result and from there into the log. It is still
returned to the caller, but registered with the run's secret masking
(:mod:`je_auto_control.utils.logging.secret_scope`) as vault values are, so
the log, the journal and the MCP audit show ``***`` in its place for the rest
of the run; and :func:`~je_auto_control.utils.executor.action_redaction.redact_result`
masks ``AC_resolve_ref``'s ``value`` and ``AC_resolve_refs``'s ``resolved`` in
the logged and displayed result.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from je_auto_control.utils.logging.secret_scope import remember_secret

_ENV_PREFIX = "env://"


def resolve_ref_command(ref: str) -> Dict[str, Any]:
    """Adapter: resolve an env:// / file:// reference; secret:// is refused (it would be recorded)."""
    from je_auto_control.utils.secret_ref import refuse_secret_refs, resolve_ref
    refuse_secret_refs(ref)
    value = resolve_ref(ref)
    _remember_env_values(ref, value)
    return {"value": value}


def resolve_refs_command(obj: Any) -> Dict[str, Any]:
    """Adapter: recursively resolve references in a structure (or JSON str); no secret://."""
    from je_auto_control.utils.secret_ref import refuse_secret_refs, resolve_refs_in
    if isinstance(obj, str):
        obj = json.loads(obj)
    refuse_secret_refs(obj)
    resolved = resolve_refs_in(obj)
    _remember_env_values(obj, resolved)
    return {"resolved": resolved}


def _remember_env_values(original: Any, resolved: Any) -> None:
    """Register every value an ``env://`` reference in ``original`` resolved to."""
    if isinstance(original, str):
        if original.startswith(_ENV_PREFIX) and isinstance(resolved, str):
            remember_secret(resolved)
        return
    for item, value in _children(original, resolved):
        _remember_env_values(item, value)


def _children(original: Any, resolved: Any) -> List[Tuple[Any, Any]]:
    """The matching ``(original, resolved)`` members of two containers of the same shape."""
    if isinstance(original, dict) and isinstance(resolved, dict):
        return [(item, resolved[key]) for key, item in original.items() if key in resolved]
    if isinstance(original, list) and isinstance(resolved, list):
        return list(zip(original, resolved))
    return []


__all__ = ["resolve_ref_command", "resolve_refs_command"]
