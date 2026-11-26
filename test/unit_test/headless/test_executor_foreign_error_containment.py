"""An error from outside the framework family is that action's failure, not the script's end.

``cv2.error``, ``sqlite3.Error`` and a plugin's own exception (deriving only
from ``Exception``) escaped the executor's per-action containment, so one of
them aborted every remaining action even under ``raise_on_error=False``. The
boundary now wraps such an error in ``AutoControlForeignException`` (the
original is its ``__cause__``) and records it like any framework error, while
assertion failures and stop / interrupt signals still propagate.
No real input or screen is involved: every command is a stub.
"""
import concurrent.futures
import sqlite3

import pytest

from je_auto_control.utils.exception.exceptions import (
    AutoControlAssertionException, AutoControlException, AutoControlForeignException,
)
from je_auto_control.utils.executor.action_executor import (
    Executor, recorded_failures, reset_recorded_failures,
)
from je_auto_control.utils.executor.run_control import ExecutionStopped


class PluginError(Exception):
    """What a third-party command defines: no framework base at all."""


def _raiser(error):
    def command():
        raise error
    return command


def _engine(error):
    engine = Executor()
    engine.event_dict["AC_foreign_boom"] = _raiser(error)
    engine.event_dict["AC_foreign_after"] = lambda: "after ran"
    return engine


def _foreign_errors():
    errors = [PluginError("plugin broke"), sqlite3.OperationalError("database is locked")]
    try:
        import cv2
    except ImportError:
        return errors
    return errors + [cv2.error("OpenCV(5) bad argument")]


@pytest.mark.parametrize("error", _foreign_errors(), ids=lambda e: type(e).__name__)
def test_a_foreign_error_is_recorded_and_the_list_goes_on(error):
    engine = _engine(error)
    reset_recorded_failures()
    record = engine.execute_action([["AC_foreign_boom"], ["AC_foreign_after"]], _validated=True)
    failure, after = list(record.values())
    assert "AutoControlForeignException" in failure
    assert type(error).__name__ in failure
    assert after == "after ran"
    assert recorded_failures() == 1


def test_raise_on_error_raises_the_wrapped_error_with_its_cause():
    original = PluginError("plugin broke")
    engine = _engine(original)
    with pytest.raises(AutoControlForeignException) as caught:
        engine.execute_action([["AC_foreign_boom"]], raise_on_error=True, _validated=True)
    assert caught.value.__cause__ is original
    assert caught.value.original is original
    assert isinstance(caught.value, AutoControlException)


@pytest.mark.parametrize("signal", [
    AutoControlAssertionException("expected failure"),
    AssertionError("a plugin's own assert"),
    ExecutionStopped("run-1", "stop requested"),
    concurrent.futures.CancelledError(),
    KeyboardInterrupt(),
    SystemExit(3),
], ids=lambda e: type(e).__name__)
def test_assertions_and_stop_signals_are_never_contained(signal):
    engine = _engine(signal)
    with pytest.raises(type(signal)):
        engine.execute_action([["AC_foreign_boom"], ["AC_foreign_after"]], _validated=True)


def test_ac_try_catches_a_foreign_error():
    engine = _engine(PluginError("plugin broke"))
    engine.event_dict["AC_foreign_recover"] = lambda: "recovered"
    record = engine.execute_action([
        ["AC_try", {"body": [["AC_foreign_boom"]], "catch": [["AC_foreign_recover"]],
                    "error_var": "why"}],
        ["AC_foreign_after"],
    ], _validated=True)
    outcome, after = list(record.values())
    assert "PluginError" in outcome["caught"]
    assert "PluginError" in engine.variables.get_value("why")
    assert after == "after ran"


def test_ac_retry_retries_a_foreign_error_then_records_exhaustion():
    calls = []

    def flaky():
        calls.append(1)
        raise PluginError("still broken")

    engine = _engine(PluginError("unused"))
    engine.event_dict["AC_foreign_flaky"] = flaky
    record = engine.execute_action([
        ["AC_retry", {"max_attempts": 2, "backoff": 0, "body": [["AC_foreign_flaky"]]}],
        ["AC_foreign_after"],
    ], _validated=True)
    outcome, after = list(record.values())
    assert len(calls) == 2
    assert "AC_retry exhausted" in outcome
    assert after == "after ran"


def test_a_foreign_error_inside_a_loop_is_recorded_per_pass():
    engine = _engine(PluginError("plugin broke"))
    reset_recorded_failures()
    record = engine.execute_action([
        ["AC_loop", {"times": 2, "body": [["AC_foreign_boom"]]}],
        ["AC_foreign_after"],
    ], _validated=True)
    assert list(record.values())[-1] == "after ran"
    assert recorded_failures() == 2


def test_a_foreign_error_in_a_parallel_branch_is_that_branch_failure():
    engine = _engine(PluginError("plugin broke"))
    reset_recorded_failures()
    record = engine.execute_action([
        ["AC_parallel", {"branches": [[["AC_foreign_boom"]], [["AC_foreign_after"]]]}],
        ["AC_foreign_after"],
    ], _validated=True)
    outcome, after = list(record.values())
    assert after == "after ran"
    assert recorded_failures() >= 1
    assert "after ran" in str(outcome)
