"""Immediate stop requests cannot overwrite or reject concurrently committed verified completion."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from je_auto_control.utils.agent_runtime import AgentTaskError
from .test_agent_runtime import managed as managed, specification


@pytest.mark.parametrize("operation", ["pause", "cancel"])
def test_completion_between_stop_read_and_write_preserves_terminal_evidence(managed, monkeypatch, operation):
    runtime, target = managed
    task = runtime.submit(specification())
    frame = runtime.observe(task.task_id)
    runtime.act(task.task_id, {"tool": "AC_increment", "observation_id": frame.observation_id})
    read, published = threading.Event(), threading.Event()
    requesting = {}
    original = runtime._row

    def interleaved_row(identifier):
        row = original(identifier)
        if threading.get_ident() == requesting.get("thread") and not read.is_set():
            read.set()
            assert published.wait(5)
        return row

    def stop_after_read():
        requesting["thread"] = threading.get_ident()
        return getattr(runtime, operation)(task.task_id)

    monkeypatch.setattr(runtime, "_row", interleaved_row)
    with ThreadPoolExecutor(max_workers=1) as worker:
        pending = worker.submit(stop_after_read)
        try:
            assert read.wait(5)
            completed = runtime.finish(task.task_id)
            assert completed.state == "succeeded"
        finally:
            published.set()
        result = pending.result(timeout=5)
    assert result.state == "succeeded"
    assert result.verification == completed.verification
    assert result.metadata["input_released"] is True
    assert target.calls == ["AC_increment"]


def test_cancel_during_resume_is_not_overwritten_by_the_requeue(managed, monkeypatch):
    runtime, _target = managed
    task = runtime.submit(specification()).task_id
    runtime.observe(task)
    assert runtime.pause(task).state == "paused"
    original = runtime.store.actions
    cancelled = []

    def interleaved(identifier):
        if not cancelled:
            with ThreadPoolExecutor(max_workers=1) as worker:
                cancelled.append(worker.submit(runtime.cancel, task).result(timeout=5).state)
        return original(identifier)

    monkeypatch.setattr(runtime.store, "actions", interleaved)
    with pytest.raises(AgentTaskError, match="stopped again"):
        runtime.resume(task)
    runtime.maintain()
    assert cancelled == ["cancelling"]
    assert runtime.get(task).state == "cancelled"


@pytest.mark.parametrize("operation,settled", [("pause", "paused"), ("cancel", "cancelled")])
def test_stop_between_failed_dispatch_check_and_review_is_kept(managed, monkeypatch, operation, settled):
    runtime, target = managed
    task = runtime.submit(specification()).task_id
    frame = runtime.observe(task)

    token = runtime._token(task)
    stopped = []

    class StoppedAfterCheck:
        """The token is read before the stop arrives, as a concurrent request can do."""

        @property
        def is_cancelled(self):
            if not stopped:
                with ThreadPoolExecutor(max_workers=1) as worker:
                    stopped.append(worker.submit(getattr(runtime, operation), task).result(timeout=5).state)
            return False

        def __getattr__(self, name):
            return getattr(token, name)

    def failing(_name, _arguments):
        runtime._tokens[task] = StoppedAfterCheck()
        raise AgentTaskError("unknown effect")

    monkeypatch.setattr(target, "perform", failing)
    with pytest.raises(AgentTaskError, match="unknown effect"):
        runtime.act(task, {"tool": "AC_increment", "observation_id": frame.observation_id})
    assert stopped == ["pausing" if operation == "pause" else "cancelling"]
    assert runtime.get(task).state == settled
