"""Run stored action lists only where both their registrant and the current caller may.

A voice command or a macro is an action list one principal stores and another
later sets off. Run with the dispatcher's rights alone, an operator's list ran
with an administrator's rights when an administrator spoke the phrase, and a
restricted user's list ran unchecked when the GUI or Python dispatched it.

:func:`registrant_and_caller` closes that: the registrant's authority is
captured when the list is stored (:class:`DeferredAuthorization`), refreshed
from its user store when the list starts (a removed user is refused), and every
step the list dispatches -- nested bodies included -- must be allowed for the
registrant *and* for whoever is running it now. A trusted local registrant or
caller (no RBAC scope) adds no restriction, so with RBAC off nothing changes.

The macro registry is one table per executor, and the module executor is
shared by every server. :func:`define_macro` keeps one principal from replacing
another's macro there: only the macro's owner, or trusted local code, may
redefine a name.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator, MutableMapping, Optional

from je_auto_control.utils.executor.dispatch import command_guard
from je_auto_control.utils.rbac.authorization import (
    AuthorizationContext, AuthorizationError, current_authorization,
)
from je_auto_control.utils.rbac.deferred import DeferredAuthorization
from je_auto_control.utils.rbac.policy import capability_for_command

_MACRO_LOCK = threading.Lock()


@contextmanager
def registrant_and_caller(authority: Optional[DeferredAuthorization], label: str) -> Iterator[None]:
    """Refuse each dispatched step the registrant or the current caller may not run.

    ``authority`` is what was captured when the list was stored; ``None`` is a
    list stored by trusted local code. ``label`` names the list in a refusal.
    """
    registrant = authority.resolve() if authority is not None else None

    def guard(name: str, _arguments: Any) -> None:
        _require(label, "registrant", registrant, name)
        _require(label, "caller", current_authorization(), name)

    with command_guard(guard):
        yield


def _require(label: str, who: str, context: Optional[AuthorizationContext], name: str) -> None:
    """Raise when ``context`` (``None`` is trusted) lacks the capability ``name`` needs."""
    if context is None:
        return
    needed = capability_for_command(name)
    if not context.allows(needed):
        raise AuthorizationError(
            f"{name} in {label} needs the {needed!r} capability; {who} {context.user_id!r} "
            f"has role {context.role!r}", capability=needed)


def _owner(authority: Optional[DeferredAuthorization]) -> Optional[tuple[str, Optional[str]]]:
    """Who stored an entry: ``None`` for trusted local code, else the user and its store."""
    context = authority.context if authority is not None else None
    return None if context is None else (context.user_id, context.store_path)


def define_macro(macros: MutableMapping[str, Any], name: str, params: list[str], body: Any) -> None:
    """Store a macro owned by the current caller; refuse replacing another principal's.

    A macro stored without an owner (trusted local code, or a table filled in
    directly from Python) belongs to trusted local code. Trusted local code
    may replace any macro; anyone else only their own.
    """
    authority = DeferredAuthorization.capture()
    owner = _owner(authority)
    with _MACRO_LOCK:
        existing = macros.get(name)
        if existing is not None and owner is not None:
            holder = _owner(existing.get("authority") if isinstance(existing, dict) else None)
            if holder != owner:
                held_by = "trusted local code" if holder is None else f"user {holder[0]!r}"
                raise AuthorizationError(
                    f"AC_define_macro: macro {name!r} is defined by {held_by}; "
                    f"user {owner[0]!r} may not redefine it")
        macros[name] = {"params": params, "body": body, "authority": authority}


def macro_authority(macro: Any) -> Optional[DeferredAuthorization]:
    """The authority a stored macro was defined with, ``None`` for trusted local code."""
    authority = macro.get("authority") if isinstance(macro, dict) else None
    return authority if isinstance(authority, DeferredAuthorization) else None


__all__ = ["define_macro", "macro_authority", "registrant_and_caller"]
