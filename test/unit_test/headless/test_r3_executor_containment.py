"""Round-3 audit regressions for executor/flow-control containment.

These pin the orchestrator-owned fixes that pair with the exception-hierarchy
reparent (every framework exception now subclasses ``AutoControlException``):

* framework exceptions are contained (recorded) by the per-action boundary
  instead of aborting the whole script;
* ``AC_try`` / ``AC_retry`` catch the whole family, not just
  ``AutoControlActionException``;
* an empty flow body is a no-op rather than an ``AutoControlActionNullException``;
* ``AC_shell_to_var`` timeouts are contained;
* ``AC_expect_poll`` treats a failed polled action as "not yet satisfied";
* ``execute_action_with_vars`` defers nested bodies (runtime ``${item}`` works);
* ``AC_parallel`` branches see custom commands / macros;
* byte-identical repeated actions keep separate record entries.

No real mouse/keyboard/screen is driven — every command is a stub.
"""
import subprocess

import pytest

from je_auto_control.utils.executor.action_executor import (
    Executor, add_command_to_executor, execute_action_with_vars, executor,
)
from je_auto_control.utils.exception.exceptions import (
    AutoControlAssertionException, AutoControlMouseException,
    ImageNotFoundException,
)


def test_framework_exception_is_contained_not_raised():
    """raise_on_error=False must record a framework error, not let it escape."""
    engine = Executor()
    engine.event_dict["AC_r3_boom"] = _raiser(ImageNotFoundException("missing"))
    record = engine.execute_action([["AC_r3_boom"]], _validated=True)
    assert any("ImageNotFoundException" in str(v) for v in record.values())


def test_ac_try_catches_framework_exception():
    """AC_try's catch branch runs when the body raises a framework error."""
    engine = Executor()
    caught = {"ran": False}
    engine.event_dict["AC_r3_boom"] = _raiser(
        AutoControlAssertionException("assert failed"))
    engine.event_dict["AC_r3_recover"] = lambda: caught.__setitem__("ran", True)
    engine.execute_action(
        [["AC_try", {"body": [["AC_r3_boom"]],
                     "catch": [["AC_r3_recover"]]}]], _validated=True)
    assert caught["ran"] is True


def test_empty_loop_body_is_noop():
    """AC_loop with an empty body completes its iterations without error."""
    engine = Executor()
    record = engine.execute_action(
        [["AC_loop", {"times": 3, "body": []}]], _validated=True)
    assert next(iter(record.values())) == 3


def test_shell_to_var_timeout_is_contained(monkeypatch):
    """A shell timeout is converted to a contained framework error."""
    from je_auto_control.utils.shell_process import shell_exec

    def _timeout(*_args, **kwargs):
        raise subprocess.TimeoutExpired(  # nosemgrep  # reason: raises an exception; no process is spawned
            cmd="x", timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(shell_exec, "run_captured", _timeout)
    engine = Executor()
    record = engine.execute_action(
        [["AC_shell_to_var", {"command": "sleep 9", "timeout": 1}]],
        _validated=True)
    assert any("timed out" in str(v) for v in record.values())


def test_expect_poll_failed_action_is_not_success():
    """A polled action that always fails must not be reported as ok=True."""
    executor.event_dict["AC_r3_pollboom"] = _raiser(
        AutoControlMouseException("nope"))
    try:
        record = executor.execute_action(
            [["AC_expect_poll", {"action": ["AC_r3_pollboom"],
                                 "timeout_s": 0.2, "interval_s": 0.05}]],
            _validated=True)
        result = next(iter(record.values()))
        assert result["ok"] is False
    finally:
        executor.event_dict.pop("AC_r3_pollboom", None)


def test_execute_action_with_vars_defers_loop_body():
    """Runtime ${item} inside a deferred body resolves per-iteration.

    The eager pre-pass previously resolved ${item} against the seed mapping —
    where it does not exist — and raised before execution.
    """
    # Read back inside the run: its scope ends with it, so nothing is left in
    # the module executor to inspect afterwards.
    record = execute_action_with_vars(
        [["AC_for_each", {"items": ["a", "b"], "as": "item",
                          "body": [["AC_set_var",
                                    {"name": "r3_last", "value": "${item}"}]]}],
         ["AC_get_var", {"name": "r3_last"}]],
        {"seed_only": 1})
    assert list(record.values())[-1] == "b"
    assert "r3_last" not in executor.variables


def test_parallel_branch_sees_custom_command():
    """A command added via add_command_to_executor works inside AC_parallel."""
    ran = {"flag": False}
    add_command_to_executor(
        {"AC_r3_custom": lambda: ran.__setitem__("flag", True)})
    try:
        executor.execute_action(
            [["AC_parallel", {"branches": [[["AC_r3_custom"]]]}]],
            _validated=True)
        assert ran["flag"] is True
    finally:
        executor.event_dict.pop("AC_r3_custom", None)


def test_duplicate_actions_recorded_separately():
    """Byte-identical actions keep separate record entries (no overwrite)."""
    engine = Executor()
    calls = {"n": 0}

    def _sometimes():
        calls["n"] += 1
        if calls["n"] == 1:
            raise AutoControlMouseException("first fails")
        return "ok"

    engine.event_dict["AC_r3_dup"] = _sometimes
    record = engine.execute_action(
        [["AC_r3_dup"], ["AC_r3_dup"]], _validated=True)
    assert len(record) == 2
    values = [str(v) for v in record.values()]
    assert any("AutoControlMouseException" in v for v in values)
    assert any(v == "ok" for v in values)


def _raiser(error):
    """Return a zero-arg callable that raises ``error`` when invoked."""
    def _raise():
        raise error
    return _raise


def test_a_missing_optional_package_is_one_failed_action():
    """ImportError from a command's lazy import aborted every later action."""
    engine = Executor()
    engine.event_dict["AC_r3_missing"] = _raiser(ModuleNotFoundError("No module named 'aiortc'"))
    engine.event_dict["AC_r3_next"] = lambda: "ran"
    record = engine.execute_action([["AC_r3_missing"], ["AC_r3_next"]])
    assert "ModuleNotFoundError" in str(record["execute: ['AC_r3_missing']"])
    assert record["execute: ['AC_r3_next']"] == "ran"


def test_try_catches_a_missing_optional_package():
    engine = Executor()
    engine.event_dict["AC_r3_missing"] = _raiser(ImportError("no backend"))
    engine.execute_action([["AC_try", {
        "body": [["AC_r3_missing"]], "catch": [["AC_set_var", {"name": "c", "value": "caught"}]]}]])
    assert engine.variables.get("c") == "caught"


def test_an_action_running_while_the_metrics_register_is_not_a_failure(monkeypatch):
    """The second of two first actions found half the metric cache: KeyError, recorded as its failure."""
    import je_auto_control.utils.observability as observability
    from je_auto_control.utils.executor import action_executor
    from je_auto_control.utils.observability.metrics import Histogram, MetricRegistry
    engine, inner = Executor(), []
    engine.event_dict["AC_r3_ok"] = lambda: "ok"

    class _Registry(MetricRegistry):
        def register(self, metric):
            if isinstance(metric, Histogram) and not inner:
                inner.append(None)
                inner[0] = engine.execute_action([["AC_r3_ok"]])   # the other thread's first action
            return super().register(metric)
    registry = _Registry()
    monkeypatch.setattr(observability, "default_registry", lambda: registry)
    monkeypatch.setattr(action_executor, "_EXECUTOR_METRIC_CACHE", {})
    assert list(engine.execute_action([["AC_r3_ok"]]).values()) == ["ok"]
    assert list(inner[0].values()) == ["ok"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
