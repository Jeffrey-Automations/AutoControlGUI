"""Scheduler defects from the 2026-09-24 audit.

In the hour repeated when clocks fall back, a cron job's next slot was
placed an hour in the past and the job fired on every tick. A run that was
in flight when its job was removed and re-registered under the same id
counted itself against the new job, which could delete it unrun.
"""
import datetime as dt
import threading
import types

import pytest

from je_auto_control.utils.run_history.history_store import HistoryStoreError
from je_auto_control.utils.scheduler import scheduler as sm

_EDT, _EST = dt.timedelta(hours=-4), dt.timedelta(hours=-5)
_SWITCH_UTC = dt.datetime(2026, 11, 1, 6, 0)          # 02:00 EDT -> 01:00 EST
_REPEAT = (dt.datetime(2026, 11, 1, 1, 0), dt.datetime(2026, 11, 1, 2, 0))


class _FallBack(dt.tzinfo):
    """US Eastern around the 2026 fall-back, with PEP 495 ``fold``."""

    def utcoffset(self, when):
        local = when.replace(tzinfo=None, fold=0)
        if local < _REPEAT[0]:
            return _EDT
        if local >= _REPEAT[1]:
            return _EST
        return _EST if when.fold else _EDT

    def dst(self, when):
        return self.utcoffset(when) - _EST

    def tzname(self, when):
        return "EST" if self.utcoffset(when) == _EST else "EDT"

    def fromutc(self, when):
        utc = when.replace(tzinfo=None)
        if utc < _SWITCH_UTC:
            return (utc + _EDT).replace(tzinfo=self)
        local = utc + _EST
        return local.replace(tzinfo=self, fold=int(_REPEAT[0] <= local < _REPEAT[1]))


_TZ = _FallBack()


class _LocalDatetime(dt.datetime):
    @classmethod
    def fromtimestamp(cls, timestamp, tz=None):
        return dt.datetime.fromtimestamp(timestamp, tz=tz or _TZ)


@pytest.fixture
def quiet_scheduler(monkeypatch):
    monkeypatch.setattr(sm, "default_history_store", types.SimpleNamespace(
        start_run=lambda *a, **k: 1, finish_run=lambda *a, **k: None))
    monkeypatch.setattr(sm, "capture_error_snapshot", lambda run_id: None)
    monkeypatch.setattr(sm, "read_executable_action_json", lambda path: [path])


def _utc(hour, minute, second=0):
    return dt.datetime(2026, 11, 1, hour, minute, second, tzinfo=dt.timezone.utc).timestamp()


def test_a_cron_job_fires_once_per_slot_through_the_repeated_hour(monkeypatch, quiet_scheduler):
    monkeypatch.setattr(sm, "_dt", types.SimpleNamespace(datetime=_LocalDatetime))
    now = [_utc(6, 0, 5)]                               # 01:00:05 EST, second pass
    monkeypatch.setattr(sm, "time", types.SimpleNamespace(time=lambda: now[0], monotonic=lambda: 0.0))
    fires = []
    scheduler = sm.Scheduler(executor=lambda actions: fires.append(now[0]))
    job = scheduler.add_cron_job("x.json", "*/15 * * * *", job_id="C")
    job.next_run_ts = now[0] - 1
    for _ in range(20):
        scheduler._tick_once()
        now[0] += 0.5
    assert len(fires) == 1
    assert job.next_run_ts == _utc(6, 15)               # 01:15 EST, not 01:15 EDT


def test_a_fixed_time_job_does_not_run_twice_on_the_fall_back_night(monkeypatch):
    monkeypatch.setattr(sm, "_dt", types.SimpleNamespace(datetime=_LocalDatetime))
    expression = sm.parse_cron("30 1 * * *")
    first = sm._next_cron_ts(expression, _utc(5, 0))    # 01:00 EDT
    assert first == _utc(5, 30)
    assert sm._next_cron_ts(expression, first) == dt.datetime(
        2026, 11, 2, 6, 30, tzinfo=dt.timezone.utc).timestamp()


def test_a_run_of_a_removed_job_leaves_its_successor_alone(quiet_scheduler):
    release, started = threading.Event(), threading.Event()
    ran = []

    def executor(actions):
        ran.append(actions[0])
        if actions[0] == "old.json":
            started.set()
            release.wait(5)

    scheduler = sm.Scheduler(executor=executor)
    old = scheduler.add_job("old.json", 0.1, job_id="J")
    old.next_run_ts = 0.0
    worker = threading.Thread(target=scheduler._tick_once)
    worker.start()
    assert started.wait(5)
    scheduler.remove_job("J")
    new = scheduler.add_job("new.json", 60, max_runs=1, job_id="J")
    release.set()
    worker.join(5)
    assert new.runs == 0
    assert [job.job_id for job in scheduler.list_jobs()] == ["J"]


@pytest.mark.parametrize("repeat", [True, False])
def test_a_failing_history_store_does_not_rerun_the_job_every_tick(monkeypatch, quiet_scheduler, repeat):
    """The run was settled after the history row, so a store failing there left the job due for ever."""
    def broken(*_args, **_kwargs):
        raise sm.default_history_store.error
    sm.default_history_store.error = HistoryStoreError("database is locked")
    sm.default_history_store.finish_run = broken
    runs = []
    scheduler = sm.Scheduler(executor=runs.append)
    job = scheduler.add_job("x.json", 60.0, repeat=repeat, job_id="J")
    job.next_run_ts = sm.time.monotonic()
    for _ in range(3):
        scheduler._tick_once()
    assert len(runs) == 1
    assert [live.runs for live in scheduler.list_jobs()] == ([1] if repeat else [])
