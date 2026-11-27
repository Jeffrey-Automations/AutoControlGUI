"""Background shutdown tracks actual workers, including models waiting before input acquisition."""
import threading

from je_auto_control.utils.agent_runtime import AgentRuntime
from je_auto_control.utils.agent_runtime.context import current_operation
from je_auto_control.utils.agent_runtime.jobs import BackgroundTasks
from je_auto_control.utils.work_queue.work_queue import WorkQueueError
from .test_agent_runtime import FakeTarget, specification


def test_shutdown_cancels_model_initialization_before_any_lease_or_display_page(tmp_path, monkeypatch):
    from je_auto_control.utils.agent_runtime import runner
    entered = threading.Event()

    class WaitingModel:
        def __init__(self, _spec):
            operation = current_operation()
            entered.set()
            while not threading.Event().wait(0.01):
                operation.checkpoint()

    runtime = AgentRuntime(tmp_path / "tasks.sqlite", targets={"fixture": FakeTarget()})
    jobs = BackgroundTasks(runtime)
    runtime.background = jobs
    monkeypatch.setattr(runner, "OllamaTaskBackend", WaitingModel)
    try:
        task = runtime.submit(specification(mode="ollama"))
        jobs.start(task.task_id)
        assert entered.wait(3)
        assert not runtime._leases
        assert runtime.get(task.task_id).state == "queued"
        jobs.close()
        assert runtime.get(task.task_id).state == "cancelled"
        assert not jobs._running
        assert all(not thread.is_alive() for thread in jobs._workers)
    finally:
        jobs.close()
        runtime.close()


def test_unstarted_accepted_work_survives_shutdown_and_late_start_cannot_launch_workers(tmp_path):
    runtime = AgentRuntime(tmp_path / "tasks.sqlite", targets={"fixture": FakeTarget()})
    jobs = BackgroundTasks(runtime)
    try:
        task = runtime.submit(specification(mode="skill", actions=[{"tool": "AC_increment", "arguments": {}}]))
        jobs.close()
        jobs.start(task.task_id)
        assert runtime.get(task.task_id).state == "queued"
        assert jobs._workers == []
    finally:
        jobs.close()
        runtime.close()


def _background(tmp_path, target):
    runtime = AgentRuntime(tmp_path / "tasks.sqlite", targets={"fixture": target})
    jobs = BackgroundTasks(runtime)
    runtime.background = jobs
    return runtime, jobs


def _wait(condition, attempts=300):
    for _attempt in range(attempts):
        if condition():
            return True
        threading.Event().wait(0.01)
    return False


def test_a_missing_expected_capture_waits_for_review_and_keeps_the_worker(tmp_path):
    runtime, jobs = _background(tmp_path, FakeTarget())
    try:
        task = runtime.submit(specification(mode="skill", actions=[
            {"tool": "AC_increment", "arguments": {}, "expect_capture": "missing"}])).task_id
        jobs.start(task)
        assert _wait(lambda: runtime.get(task).state == "waiting_user")
        assert all(thread.is_alive() for thread in jobs._workers)
        assert task not in runtime._leases
    finally:
        jobs.close()
        runtime.close()


def test_an_uncontained_lookup_failure_keeps_every_worker_and_releases_input(tmp_path):
    class Broken(FakeTarget):
        def observe(self):
            raise KeyError("foreign adapter")

    runtime, jobs = _background(tmp_path, Broken())
    try:
        task = runtime.submit(specification(mode="skill", actions=[
            {"tool": "AC_increment", "arguments": {}}])).task_id
        jobs.start(task)
        assert _wait(lambda: runtime.get(task).state == "waiting_user" and not jobs._running)
        assert all(thread.is_alive() for thread in jobs._workers)
        assert task not in runtime._leases
    finally:
        jobs.close()
        runtime.close()


def test_failed_cleanup_after_a_cancel_neither_kills_the_worker_nor_drops_the_cancel(tmp_path):
    class Stuck(FakeTarget):
        def observe(self):
            runtime.cancel(task)
            raise OSError("helper was lost")

        def cleanup(self):
            raise RuntimeError("cleanup is unconfirmed")

    target = Stuck()
    runtime, jobs = _background(tmp_path, target)
    try:
        task = runtime.submit(specification(mode="skill", actions=[
            {"tool": "AC_increment", "arguments": {}}])).task_id
        jobs.start(task)
        assert _wait(lambda: runtime.get(task).state != "queued" and not jobs._running)
        assert _wait(lambda: not jobs._running)
        assert runtime.get(task).state == "cancelling", "a failed worker cannot turn a cancel into a resumable state"
        assert all(thread.is_alive() for thread in jobs._workers)
    finally:
        target.cleanup = lambda: None
        jobs.close()
        runtime.close()


def test_a_busy_queue_database_does_not_end_a_worker(tmp_path, monkeypatch):
    runtime, jobs = _background(tmp_path, FakeTarget())
    polled = threading.Event()

    def busy():
        polled.set()
        raise WorkQueueError("database is locked")

    monkeypatch.setattr(jobs._queue, "get_next", busy)
    try:
        task = runtime.submit(specification(mode="skill", actions=[
            {"tool": "AC_increment", "arguments": {}}])).task_id
        jobs.start(task)
        assert polled.wait(3)
        assert not _wait(lambda: not all(thread.is_alive() for thread in jobs._workers), attempts=30)
    finally:
        jobs.close()
        runtime.close()
