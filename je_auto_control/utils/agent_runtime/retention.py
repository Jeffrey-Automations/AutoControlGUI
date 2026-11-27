"""Thirty-day cleanup of stopped tasks and exclusively owned runtime artifacts."""
from __future__ import annotations

import time
from typing import Any

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.policy import owns_task
from je_auto_control.utils.agent_runtime.dag_retention import prune_batches, protects_task
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.rbac.authorization import current_authorization

_ERRORS = (AutoControlException, OSError, RuntimeError, ValueError, TypeError, LookupError)


def prune_tasks(runtime: Any, keep_days: int = 30) -> dict[str, Any]:
    """Prune at most one thousand expired terminal tasks visible to this caller per sweep."""
    if isinstance(keep_days, bool) or not isinstance(keep_days, int) or not 1 <= keep_days <= 3650:
        raise AgentTaskError("retention must be between one and 3650 days")
    identity = current_authorization()
    cutoff = time.time() - keep_days * 86400
    batches = prune_batches(runtime, cutoff, identity)
    if identity is None or identity.role == "admin":
        _orphan_deliveries(runtime.store)
    with runtime.store.connection() as connection:
        identifiers = [row[0] for row in connection.execute(
            "SELECT id FROM agent_tasks WHERE state IN ('succeeded','failed','cancelled','timed_out') "
            "AND updated<? ORDER BY updated LIMIT 1000", (cutoff,))]
    return {"deleted": _prune_each(runtime, identifiers, identity), "keep_days": keep_days, **batches}


def _prune_each(runtime: Any, identifiers: list[str], identity: Any) -> list[str]:
    deleted: list[str] = []
    failure: Exception | None = None
    for task_id in identifiers:
        try:
            if _prune_task(runtime, task_id, identity):
                deleted.append(task_id)
        except _ERRORS as error:  # a task needing review stays; it must not hold back the ones after it
            failure = failure or error
    if failure is not None:
        raise failure
    return deleted


def _prune_task(runtime: Any, task_id: str, identity: Any) -> bool:
    # pylint: disable-next=protected-access  # reason: prune under the same task lock as every lifecycle transition
    with runtime._lock(task_id):
        row = runtime.store.get(task_id)
        if not owns_task(row["owner"], identity) or _preserve_task(runtime, task_id):
            return False
        # pylint: disable-next=protected-access  # reason: reap retained context before removing its source identity
        runtime._retained_browsers.discard(task_id)
        runtime.evidence.remove(task_id)
        _remove_metadata(runtime.store, task_id)
        # pylint: disable-next=protected-access  # reason: drop only this expired task's runtime-owned caches
        for cache in (runtime._tokens, runtime._stop_final, runtime._observations, runtime._observation_times,
                      runtime._completion_targets):
            cache.pop(task_id, None)
        return True


def _preserve_task(runtime: Any, task_id: str) -> bool:
    # pylint: disable-next=protected-access  # reason: never prune live input ownership or a still-unwinding dispatch
    if task_id in runtime._leases or task_id in runtime._executing or protects_task(runtime.store, task_id):
        return True
    with runtime.store.connection() as connection:
        return connection.execute("SELECT 1 FROM agent_task_recoveries r JOIN agent_tasks t ON t.id=r.task_id "
                                  "WHERE r.source_task=?", (task_id,)).fetchone() is not None


def _remove_metadata(store: Any, task_id: str) -> None:
    with store.connection(write=True) as connection:
        connection.execute("DELETE FROM agent_reviews WHERE task_id=?", (task_id,))
        connection.execute("DELETE FROM agent_actions WHERE task_id=?", (task_id,))
        connection.execute("DELETE FROM agent_tasks WHERE id=?", (task_id,))
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='work_items'").fetchone():
            connection.execute("DELETE FROM work_items WHERE queue='agent_runtime' AND reference=? "
                               "AND status!='in_progress'", (task_id,))


def _orphan_deliveries(store: Any) -> None:
    with store.connection(write=True) as connection:
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='work_items'").fetchone():
            connection.execute("DELETE FROM work_items WHERE queue='agent_runtime' AND status!='in_progress' "
                               "AND NOT EXISTS (SELECT 1 FROM agent_tasks WHERE id=work_items.reference)")
