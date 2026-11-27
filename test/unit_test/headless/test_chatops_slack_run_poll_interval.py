"""The Slack bot polls faster while a ``/run`` is going, so ``/stop`` lands quickly.

``SlackBot`` read the channel every ``poll_interval_s`` (5 s) whatever it was
doing, so a ``/stop`` for its own run waited up to that long. It now polls
every ``run_poll_interval_s`` (1 s) while a background command runs, from the
very wait after the run starts, and still holds every poll back for a Slack
``429``'s ``Retry-After``.

Slack is faked in memory (no network). Most tests drive the poll loop on a
fake clock whose waits return at once; the two that need a real thread wait
well under a second.
"""
import math
import threading

import pytest

from je_auto_control.utils.chatops import CommandResult, CommandRouter, SlackBot, SlackError
from je_auto_control.utils.chatops import slack_bot as module

_BOUND = 5.0  # a safety bound on joins and releases, never waited out


class _Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class _Wake:
    """Stands in for the bot's wake event: every wait runs its whole timeout at once."""

    def __init__(self, clock):
        self._clock = clock
        self.waits = []

    def wait(self, timeout):
        self.waits.append(timeout)
        self._clock.now += timeout
        return False

    def set(self):
        """A wake-up changes nothing on a clock that already jumped."""

    def clear(self):
        """Nothing to clear."""


class _Slack:
    """``perform_call`` answered from memory; records when each history read happened."""

    def __init__(self, clock=None):
        self._clock = clock
        self._lock = threading.Lock()
        self.pending = []
        self.limited = []  # Retry-After values to answer the next history reads with
        self.reads = []
        self.read_event = threading.Event()

    def say(self, ts, text):
        with self._lock:
            self.pending.append({"ts": str(ts), "user": "U1", "text": text})

    def __call__(self, call):
        method = call["url"].split("/api/", 1)[1].split("?", 1)[0]
        if method == "auth.test":
            return _reply({"ok": True, "user_id": "U_BOT"})
        if method != "conversations.history":
            return _reply({"ok": True})
        with self._lock:
            self.reads.append(self._clock() if self._clock else None)
            self.read_event.set()
            if self.limited:
                return _reply({"ok": False, "error": "ratelimited"}, status=429,
                              headers={"Retry-After": self.limited.pop(0)})
            batch = list(reversed(self.pending))
            self.pending.clear()
        return _reply({"ok": True, "messages": batch})


def _reply(body, status=200, headers=None):
    return {"status": status, "ok": status < 400, "headers": headers or {}, "json": body}


class _Run:
    """A ``/run`` command that holds its worker until released."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, _argv, _context):
        self.entered.set()
        self.release.wait(_BOUND)
        return CommandResult(text="run done")


@pytest.fixture
def run():
    command = _Run()
    yield command
    command.release.set()


def _bot(tmp_path, monkeypatch, slack, run, **options):
    router = CommandRouter()
    router.register("run", run)
    made = SlackBot(token="xoxb-fake", channel_id="C1", router=router,
                    last_seen_ts="0", state_path=str(tmp_path / "C1.json"), **options)
    monkeypatch.setattr(module, "perform_call", slack)
    return made


def _on_fake_clock(made, clock):
    made._clock = clock
    made._wake = _Wake(clock)
    return made


def _gaps(times):
    return [round(later - earlier, 6) for earlier, later in zip(times, times[1:])]


def _stop(made, run):
    run.release.set()
    assert made.stop(timeout=_BOUND) is True


# --- the interval in force --------------------------------------------------

def test_idle_bot_polls_at_the_idle_interval(tmp_path, monkeypatch, run):
    clock = _Clock()
    slack = _Slack(clock)
    made = _on_fake_clock(_bot(tmp_path, monkeypatch, slack, run, poll_interval_s=5.0), clock)
    made.run_forever(max_iterations=3)
    assert _gaps(slack.reads) == [5.0, 5.0]


def test_a_running_command_polls_at_the_run_interval(tmp_path, monkeypatch, run):
    clock = _Clock()
    slack = _Slack(clock)
    made = _on_fake_clock(_bot(tmp_path, monkeypatch, slack, run, poll_interval_s=5.0,
                               run_poll_interval_s=1.0), clock)
    slack.say(1, "/run job.json")
    made.run_forever(max_iterations=4)
    assert run.entered.is_set()
    # The wait right after the poll that started the run is already the short one.
    assert _gaps(slack.reads) == [1.0, 1.0, 1.0]
    _stop(made, run)


def test_the_idle_interval_comes_back_when_the_run_ends(tmp_path, monkeypatch, run):
    clock = _Clock()
    slack = _Slack(clock)
    made = _on_fake_clock(_bot(tmp_path, monkeypatch, slack, run, poll_interval_s=5.0,
                               run_poll_interval_s=0.5), clock)
    slack.say(1, "/run job.json")
    made.run_forever(max_iterations=2)
    run.release.set()
    assert made.wait_idle(timeout=_BOUND) is True
    made.run_forever(max_iterations=3)
    # 0.5 while running; the second loop polls at once, then idles at 5 s.
    assert _gaps(slack.reads) == [0.5, 0.0, 5.0, 5.0]


def test_a_run_started_during_an_idle_wait_shortens_it_at_once(tmp_path, monkeypatch, run):
    """Real clock: the loop sits in a 5 s idle wait when a run starts beside it."""
    slack = _Slack()
    made = _bot(tmp_path, monkeypatch, slack, run, poll_interval_s=5.0,
                run_poll_interval_s=0.05)
    loop = threading.Thread(target=made.run_forever, daemon=True)
    loop.start()
    try:
        assert slack.read_event.wait(_BOUND), "the loop never polled"
        slack.read_event.clear()
        slack.say(1, "/run job.json")
        assert made.poll_once() == 1  # starts the run off the loop's thread
        assert run.entered.wait(_BOUND)
        slack.read_event.clear()
        assert slack.read_event.wait(0.9), "the loop kept waiting out its idle interval"
    finally:
        _stop(made, run)
        loop.join(_BOUND)
    assert not loop.is_alive()


def test_stop_ends_an_idle_wait_promptly(tmp_path, monkeypatch, run):
    slack = _Slack()
    made = _bot(tmp_path, monkeypatch, slack, run, poll_interval_s=30.0,
                run_poll_interval_s=1.0)
    loop = threading.Thread(target=made.run_forever, daemon=True)
    loop.start()
    assert slack.read_event.wait(_BOUND), "the loop never polled"
    assert made.stop(timeout=_BOUND) is True
    loop.join(0.9)
    assert not loop.is_alive(), "stop() did not wake the poll loop"


# --- Slack rate limits ------------------------------------------------------

def test_retry_after_holds_back_the_fast_interval(tmp_path, monkeypatch, run):
    clock = _Clock()
    slack = _Slack(clock)
    made = _on_fake_clock(_bot(tmp_path, monkeypatch, slack, run, poll_interval_s=5.0,
                               run_poll_interval_s=1.0), clock)
    slack.say(1, "/run job.json")
    made.run_forever(max_iterations=2)  # starts the run, then one fast poll
    slack.limited.append("30")
    made.run_forever(max_iterations=3)  # rate limited, then two more polls
    # Polls at 0 (the run starts) and 1; the second loop's first poll, also at 1,
    # is answered 429: nothing more until its Retry-After has passed, then 1 s again.
    assert _gaps(slack.reads) == [1.0, 0.0, 30.0, 1.0]
    _stop(made, run)


def test_retry_after_holds_back_the_idle_interval(tmp_path, monkeypatch, run):
    clock = _Clock()
    slack = _Slack(clock)
    made = _on_fake_clock(_bot(tmp_path, monkeypatch, slack, run, poll_interval_s=5.0), clock)
    slack.limited.append("42")
    made.run_forever(max_iterations=3)
    assert _gaps(slack.reads) == [42.0, 5.0]


def test_a_rate_limit_without_retry_after_falls_back_to_the_back_off(tmp_path, monkeypatch, run):
    clock = _Clock()
    slack = _Slack(clock)
    made = _on_fake_clock(_bot(tmp_path, monkeypatch, slack, run, poll_interval_s=5.0), clock)
    slack.limited.append("soon")
    made.run_forever(max_iterations=2)
    assert _gaps(slack.reads) == [7.0]  # 5 s interval + the 2 s first back-off


# --- validation -------------------------------------------------------------

def test_the_run_interval_defaults_to_one_second(tmp_path, monkeypatch, run):
    made = _bot(tmp_path, monkeypatch, _Slack(), run)
    assert made.run_poll_interval_s == 1.0
    assert made.poll_interval_s == 5.0


@pytest.mark.parametrize("value", [0, 0.0, -1.0, math.nan, math.inf, 5.5, True, "1", None])
def test_a_bad_run_interval_is_refused(tmp_path, monkeypatch, run, value):
    with pytest.raises(SlackError, match="run_poll_interval_s"):
        _bot(tmp_path, monkeypatch, _Slack(), run, poll_interval_s=5.0,
             run_poll_interval_s=value)


@pytest.mark.parametrize("value", [0.01, 1, 5.0])
def test_a_run_interval_up_to_the_idle_one_is_accepted(tmp_path, monkeypatch, run, value):
    made = _bot(tmp_path, monkeypatch, _Slack(), run, poll_interval_s=5.0,
                run_poll_interval_s=value)
    assert made.run_poll_interval_s == float(value)
    assert isinstance(made.run_poll_interval_s, float)


@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_a_non_finite_idle_interval_is_refused(tmp_path, monkeypatch, run, value):
    with pytest.raises(SlackError, match="poll_interval_s"):
        _bot(tmp_path, monkeypatch, _Slack(), run, poll_interval_s=value)
