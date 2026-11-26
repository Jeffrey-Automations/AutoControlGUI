"""Emergency stop of every visible task; a busy DAG batch is fenced in the background, never awaited.

Input stops first: every visible task's host token is cancelled before anything can wait.
A DAG batch is then paused under its lifecycle lock, but a batch whose lock is held by a
running operation (a slow host, say) is not awaited. It is marked as fencing instead, which
refuses its coordinators any further progress the moment they next take the lock or check
their attempt (:func:`refuse_while_fencing`), and a background thread pauses it once the
operation ends, cancels any task that operation admitted, and reports what failed: through
the log at once, and in ``cleanup_errors`` of the next stop. The stop returns as soon as the
visible tasks are cancelled, listing the batches still fencing in ``batch_fence_pending``.
"""
from __future__ import annotations

import json
import threading
import time
import weakref
from typing import Any

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.models import AgentTaskResult, freeze
from je_auto_control.utils.agent_runtime.policy import owns_task
from je_auto_control.utils.agent_runtime.runtime_lock import cancel_tokens
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.rbac.authorization import current_authorization
from je_auto_control.utils.rbac.deferred import DeferredAuthorization

_ERRORS = (AutoControlException, OSError, RuntimeError, TypeError, ValueError, LookupError)
_REPORTED = 1000


class _Fences:
    """Per runtime: batches whose pause is pending, and background failures not yet reported."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.batches: set[str] = set()
        self.errors: list[dict[str, str]] = []


_REGISTRY: weakref.WeakKeyDictionary[Any, _Fences] = weakref.WeakKeyDictionary()
_REGISTRY_LOCK = threading.Lock()


def _fences(runtime: Any) -> _Fences:
    with _REGISTRY_LOCK:
        return _REGISTRY.setdefault(runtime, _Fences())


def mark_fencing(runtime: Any, batch_id: str) -> None:
    """Refuse this batch's coordinators any progress until its pause has been attempted."""
    fences = _fences(runtime)
    with fences.lock:
        fences.batches.add(batch_id)


def unmark_fencing(runtime: Any, batch_id: str) -> None:
    """The pause was attempted; the batch's durable state governs it again."""
    fences = _fences(runtime)
    with fences.lock:
        fences.batches.discard(batch_id)


def refuse_while_fencing(runtime: Any, batch_id: str) -> None:
    """Raise while a stop's pause of this batch is still pending."""
    fences = _fences(runtime)
    with fences.lock:
        fencing = batch_id in fences.batches
    if fencing:
        raise AgentTaskError("batch is being stopped; its pause is still pending")


def stop_all_tasks(runtime: Any) -> dict[str, Any]:
    """Cancel every visible task; operators cannot stop another principal's work."""
    # pylint: disable=protected-access  # reason: the runtime's own stop path, moved out of runtime.py
    cancel_tokens(runtime._stop_final, runtime._token, visible_live_ids(runtime))
    busy: list[str] = []
    errors = runtime.batches.stop_all(deferred=busy)
    identifiers = cancel_tokens(runtime._stop_final, runtime._token, visible_live_ids(runtime))
    results, task_errors = stop_tasks(runtime, identifiers)
    if busy:
        threading.Thread(target=_fence_in_background, name="AgentStopFence", daemon=True,
                         args=(runtime, busy, set(identifiers), DeferredAuthorization.capture())).start()
    fences = _fences(runtime)
    with fences.lock:
        earlier, fences.errors = fences.errors, []
    return {"tasks": results, "requested": len(identifiers),
            "cleanup_errors": (errors + task_errors + earlier)[:_REPORTED], "batch_fence_pending": busy}


def stop_tasks(runtime: Any, identifiers: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Mark tasks cancelling, settle those without input at once and cancel the rest one by one."""
    with runtime.store.connection(write=True) as connection:
        connection.executemany("UPDATE agent_tasks SET state='cancelling',updated=? WHERE id=? "
            "AND state NOT IN ('succeeded','failed','cancelled','timed_out')",
            [(time.time(), identifier) for identifier in identifiers])
    queued = _cancel_without_input(runtime, identifiers)
    snapshots = _stop_snapshots(runtime, [task_id for task_id in identifiers[:_REPORTED] if task_id in queued])
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for task_id in identifiers:
        if task_id in queued:
            if task_id in snapshots:
                results.append(snapshots[task_id])
            continue
        try:
            result = runtime.cancel(task_id)
            if len(results) < _REPORTED:
                results.append(result.to_dict())
        except _ERRORS as error:
            errors.append({"task_id": task_id, "error": type(error).__name__})
    return results, errors


def _fence_in_background(runtime: Any, busy: list[str], stopped: set[str], actor: DeferredAuthorization) -> None:
    errors: list[dict[str, str]] = []
    try:
        with actor.context_scope():
            for batch_id in busy:
                try:
                    runtime.batches.control("pause_batch", {"batch_id": batch_id})
                except _ERRORS as error:
                    errors.append({"batch_id": batch_id, "error": type(error).__name__})
                finally:
                    unmark_fencing(runtime, batch_id)
            # Tasks the fenced operations admitted before their pause; the stop already owns the rest.
            late = [task_id for task_id in visible_live_ids(runtime) if task_id not in stopped]
            # pylint: disable-next=protected-access  # reason: the runtime's own stop path
            cancel_tokens(runtime._stop_final, runtime._token, late)
            errors.extend(stop_tasks(runtime, late)[1])
    except _ERRORS as error:  # reason: reported below and in the next stop; a stop has no caller left to raise to
        errors.append({"error": type(error).__name__})
    finally:
        for batch_id in busy:
            unmark_fencing(runtime, batch_id)
    if errors:
        autocontrol_logger.warning("agent stop fencing needs review: %s", [item["error"] for item in errors][:10])
        fences = _fences(runtime)
        with fences.lock:
            fences.errors = (fences.errors + errors)[:_REPORTED]


def visible_live_ids(runtime: Any) -> list[str]:
    """Unfinished tasks the current caller owns."""
    identity = current_authorization()
    with runtime.store.connection() as connection:
        rows = connection.execute("SELECT id,owner FROM agent_tasks "
            "WHERE state NOT IN ('succeeded','failed','cancelled','timed_out')").fetchall()
    return [row["id"] for row in rows if owns_task(json.loads(row["owner"]), identity)]


def _stop_snapshots(runtime: Any, identifiers: list[str]) -> dict[str, dict[str, Any]]:
    if not identifiers:
        return {}
    with runtime.store.connection() as connection:
        connection.execute("CREATE TEMP TABLE agent_stop_page (id TEXT PRIMARY KEY)")
        connection.executemany("INSERT INTO agent_stop_page VALUES (?)", [(item,) for item in identifiers])
        rows = connection.execute("SELECT t.*,p.task_id AS report_pending FROM agent_tasks t "
            "JOIN agent_stop_page s ON s.id=t.id LEFT JOIN agent_evidence_pending p ON p.task_id=t.id").fetchall()
    return {row["id"]: AgentTaskResult(row["id"], row["state"], json.loads(row["spec"])["goal"], row["reason"],
            row["steps"], tuple(freeze(json.loads(row["verification"]))),
            freeze({"details_deferred": True, "report_pending": row["report_pending"] is not None})).to_dict()
            for row in rows}


def _cancel_without_input(runtime: Any, identifiers: list[str]) -> set[str]:
    # pylint: disable=protected-access  # reason: the runtime's own stop path, moved out of runtime.py
    with runtime._mutex:
        queued = {task_id for task_id in identifiers if task_id not in runtime._leases
                  and task_id not in runtime._executing}
    with runtime.store.connection(write=True) as connection:
        connection.executemany("UPDATE agent_tasks SET state='cancelled',updated=? "
                               "WHERE id=? AND state='cancelling'", [(time.time(), item) for item in queued])
    if runtime.background is not None:
        runtime.evidence.defer(list(queued))
    else:
        for task_id in queued:
            runtime.evidence.publish(task_id)
    return queued
