"""Durable background dispatch over the existing fenced WorkQueue implementation."""
from __future__ import annotations

import threading
from contextvars import Context
from typing import Any

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.models import TERMINAL
from je_auto_control.utils.agent_runtime.runner import run_task
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.work_queue.work_queue import WorkQueue

_ERRORS = (AutoControlException, OSError, RuntimeError, TypeError, ValueError, LookupError)
# A failed worker cannot overwrite a stop someone requested or a pause that already took effect.
_STOPPING = TERMINAL | {"pausing", "paused", "cancelling"}


class BackgroundTasks:
    """A bounded service worker pool; accepted jobs survive client and view shutdown."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._queue = WorkQueue(runtime.store.path, "agent_runtime")
        self._workers: list[threading.Thread] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._running: set[str] = set()
        with runtime.store.connection(write=True) as connection:
            connection.execute("UPDATE work_items SET status='new',claim=claim+1 WHERE queue='agent_runtime' "
                               "AND status='in_progress'")

    def start_pending(self) -> None:
        """Recover queued deliveries after exclusive service ownership has been established."""
        with self._runtime.store.connection() as connection:
            identifiers = [row[0] for row in connection.execute("SELECT id FROM agent_tasks WHERE state='queued'")]
        for task_id in identifiers:
            self.start(task_id)

    def start(self, task_id: str) -> None:
        """Persist internal task delivery; external tasks stay under client control."""
        row = self._runtime._row(task_id)
        if row["spec"]["mode"] == "external" or row["state"] != "queued":
            return
        self._queue.add({"task_id": task_id}, reference=task_id)
        with self._lock:
            if self._workers or self._stop.is_set():
                return
            for index in range(4):
                thread = threading.Thread(target=lambda: Context().run(self._drain),
                                          name=f"AgentWorker-{index}", daemon=True)
                self._workers.append(thread)
                thread.start()

    def _drain(self) -> None:
        while not self._stop.is_set():
            item = self._next_item()
            if item is None:
                self._stop.wait(0.1)
                continue
            task_id = item.data["task_id"]
            with self._lock:
                if self._stop.is_set():
                    self._queue.defer(item.id, claim=item.claim)
                    return
                self._running.add(task_id)
            self._run_item(item)

    def _next_item(self) -> Any:
        try:
            return self._queue.get_next()
        except AutoControlException as error:  # a busy database must not cost the pool a worker
            autocontrol_logger.warning("agent work queue needs review: %s", type(error).__name__)
            return None

    def _run_item(self, item: Any) -> None:
        task_id = item.data["task_id"]
        try:
            outcome = run_task(self._runtime, task_id)
            if outcome.state == "queued":
                self._queue.defer(item.id, claim=item.claim)
                self._stop.wait(0.25)
            else:
                self._queue.complete(item.id, claim=item.claim, output=outcome.to_dict())
                self._handoff_resume(task_id)
        except _ERRORS as error:
            self._fail_item(item, error)
        finally:
            with self._lock:
                self._running.discard(task_id)

    def _fail_item(self, item: Any, error: Exception) -> None:
        try:
            self._queue.fail(item.id, type(error).__name__, kind="business", claim=item.claim)
        except _ERRORS as failure:  # the delivery record cannot keep the task itself from review
            autocontrol_logger.warning("agent delivery record needs review: %s", type(failure).__name__)
        try:
            self._review_failure(item.data["task_id"])
        except _ERRORS as failure:  # a failed cleanup keeps its lease and must not end the worker
            autocontrol_logger.warning("agent input retirement needs review: %s", type(failure).__name__)

    def _handoff_resume(self, task_id: str) -> None:
        with self._runtime.store.connection() as connection:
            row = connection.execute("SELECT state FROM agent_tasks WHERE id=?", (task_id,)).fetchone()
        if row is not None and row["state"] == "queued" and not self._stop.is_set():
            self.start(task_id)

    def _review_failure(self, task_id: str) -> None:
        with self._runtime.store.connection() as connection:
            row = connection.execute("SELECT state FROM agent_tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            return
        if row["state"] not in _STOPPING:
            self._runtime.store.transition(task_id, row["state"], "waiting_user",
                                           reason="background work requires review")
        self._runtime._retire(task_id)

    def close(self) -> None:
        """Cancel running tasks, retire workers, then permit the service to release input."""
        with self._lock:
            self._stop.set()
            running = tuple(self._running)
        for task_id in running:
            self._runtime._token(task_id).cancel()
        for task_id in running:
            self._runtime.cancel(task_id)
        for thread in self._workers:
            thread.join(timeout=2)
            if thread.is_alive():
                raise AgentTaskError("an agent worker has not retired yet")
