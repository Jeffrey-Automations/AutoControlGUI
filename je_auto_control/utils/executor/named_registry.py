"""Process-wide name-to-state tables behind the executor's named commands, capped in size.

``AC_cas_put``, ``AC_dedup_check``, ``AC_idempotency_begin``,
``AC_bulkhead_run``, ``AC_sequence_observe`` and ``AC_outbox_enqueue`` keep
their state under a caller-chosen name for the life of the process. Every new
name added a table entry, so a caller could grow the process without bound.

A :class:`NamedRegistry` holds at most :data:`MAX_REGISTRY_NAMES` names. A
name already present keeps working at the cap; a new one is refused with
:class:`RegistryFullError`. Nothing is ever evicted: an entry is live state
(a held bulkhead permit, an idempotency key in flight) that an LRU would
silently drop. None of these registries has a delete or reset command, so the
names are released only when the process ends.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from je_auto_control.utils.exception.exceptions import AutoControlActionException

#: The most names one registry holds.
MAX_REGISTRY_NAMES = 1024


class RegistryFullError(AutoControlActionException):
    """A named registry is at its cap and was asked to create one more name."""


class NamedRegistry:
    """A bounded, thread-safe ``name -> state`` table; existing names are never evicted."""

    def __init__(self, label: str, commands: str, *, limit: int = MAX_REGISTRY_NAMES) -> None:
        """``label`` names the registry and ``commands`` the commands that fill it, in a refusal."""
        self.label = label
        self.commands = commands
        self.limit = limit
        self._entries: Dict[Any, Any] = {}
        self._lock = threading.Lock()

    def setdefault(self, name: Any, default: Any) -> Any:
        """The state under ``name``, storing ``default`` there first if the name is new.

        Raises :class:`RegistryFullError` for a new name once :attr:`limit`
        names are held; ``default`` is then discarded.
        """
        with self._lock:
            if name in self._entries:
                return self._entries[name]
            if len(self._entries) >= self.limit:
                raise RegistryFullError(
                    f"the {self.label} registry ({self.commands}) already holds {self.limit} names; "
                    f"refusing to create {_shown(name)}. Existing names keep working; this registry "
                    "has no delete or reset command, so its names are released when the process ends")
            self._entries[name] = default
            return default

    def get(self, name: Any, default: Optional[Any] = None) -> Any:
        """The state under ``name``, or ``default``; never creates a name."""
        with self._lock:
            return self._entries.get(name, default)

    def __contains__(self, name: Any) -> bool:
        with self._lock:
            return name in self._entries

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


def _shown(name: Any) -> str:
    """``repr(name)``, bounded so a huge name does not flood the error."""
    text = repr(name)
    return text if len(text) <= 80 else text[:77] + "..."


__all__ = ["MAX_REGISTRY_NAMES", "NamedRegistry", "RegistryFullError"]
