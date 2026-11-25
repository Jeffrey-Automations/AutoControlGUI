"""Headless tests for the saga / compensating-rollback orchestrator. Steps are
plain callables recording call order — fully deterministic, no side effects.
Pure stdlib, no Qt imports."""
import je_auto_control as ac
from je_auto_control.utils.saga import Saga


def _recorder():
    log = []
    return log, (lambda tag: (lambda: log.append(tag)))


def test_all_steps_succeed_no_compensation():
    log, make = _recorder()
    result = (Saga()
              .step("a", make("do-a"), make("undo-a"))
              .step("b", make("do-b"), make("undo-b"))
              .run())
    assert result.ok is True
    assert result.completed == ["a", "b"]
    assert result.compensated == []
    assert log == ["do-a", "do-b"]


def test_failure_triggers_lifo_compensation():
    log, make = _recorder()

    def boom():
        raise RuntimeError("step c failed")

    result = (Saga()
              .step("a", make("do-a"), make("undo-a"))
              .step("b", make("do-b"), make("undo-b"))
              .step("c", boom, make("undo-c"))
              .run())
    assert result.ok is False
    assert result.failed_step == "c"
    assert "step c failed" in result.error
    assert result.completed == ["a", "b"]          # c never completed
    assert result.compensated == ["b", "a"]        # LIFO over completed
    # forward a,b then undo b,a (c's action raised before completing)
    assert log == ["do-a", "do-b", "undo-b", "undo-a"]


def test_steps_without_compensation_are_skipped():
    log, make = _recorder()

    def boom():
        raise ValueError("x")

    result = (Saga()
              .step("a", make("do-a"))             # no compensation
              .step("b", make("do-b"), make("undo-b"))
              .step("c", boom)
              .run())
    assert result.failed_step == "c"
    assert result.compensated == ["b"]             # a had none to run
    assert log == ["do-a", "do-b", "undo-b"]


def test_compensation_failure_is_best_effort():
    log, make = _recorder()

    def bad_undo():
        raise RuntimeError("undo failed")

    def boom():
        raise RuntimeError("fail")

    result = (Saga()
              .step("a", make("do-a"), make("undo-a"))
              .step("b", make("do-b"), bad_undo)    # its undo raises
              .step("c", boom, None)
              .run())
    # rollback continues past the failing compensation; a still undone, and
    # b -- whose undo raised -- is reported as an error, not as compensated
    assert result.compensated == ["a"]
    assert result.compensation_errors == {"b": "undo failed"}
    assert log == ["do-a", "do-b", "undo-a"]       # undo-a still ran


# --- wiring ---------------------------------------------------------------

def test_executor_round_trip_success():
    rec = ac.execute_action([[
        "AC_run_saga",
        {"steps": [
            {"name": "q",
             "action": [["AC_json_query", {"data": {"a": 1}, "path": "$.a"}]]},
        ]},
    ]])
    out = next(v for v in rec.values() if isinstance(v, dict)
               and "completed" in v)
    assert out["ok"] is True
    assert out["completed"] == ["q"]


def test_wiring():
    assert "AC_run_saga" in ac.executor.known_commands()
    from je_auto_control.utils.mcp_server.tools import (
        build_default_tool_registry)
    names = {t.name for t in build_default_tool_registry()}
    assert "ac_run_saga" in names
    from je_auto_control.gui.script_builder.command_schema import _build_specs
    cmds = {s.command for s in _build_specs()}
    assert "AC_run_saga" in cmds


def test_facade_exports():
    for attr in ("Saga", "SagaResult", "run_saga"):
        assert hasattr(ac, attr)
        assert attr in ac.__all__


def test_a_stop_or_cancel_rolls_back_and_then_propagates():
    """A stop was reported as an ordinary failed step, so the caller carried on."""
    from concurrent.futures import CancelledError
    import pytest
    from je_auto_control.utils.exception.control_signals import OperationCancelledError
    from je_auto_control.utils.executor.run_control import ExecutionStopped
    for signal in (ExecutionStopped("run"), OperationCancelledError("request"), CancelledError()):
        log = []

        def interrupted(raised=signal):
            raise raised

        saga = Saga().step("a", lambda: log.append("a"), lambda: log.append("undo-a")).step("b", interrupted)
        with pytest.raises(type(signal)) as caught:
            saga.run()
        assert caught.value is signal
        assert log == ["a", "undo-a"]


def test_rollback_runs_to_its_end_while_a_stop_unwinds():
    """Each compensation raised the same stop at its first checkpoint, so nothing was undone."""
    import pytest
    from je_auto_control.utils.executor.run_control import (
        ExecutionStopped, StopToken, checkpoint, stoppable_run,
    )
    token = StopToken("saga-stop")
    log = []

    def undo(name):
        def run():
            checkpoint()
            log.append(name)
        return run

    def stop_here():
        token.stop("test")
        checkpoint()

    saga = Saga().step("a", lambda: None, undo("a")).step("b", lambda: None, undo("b")).step("c", stop_here)
    with stoppable_run(token=token):
        with pytest.raises(ExecutionStopped):
            saga.run()
    assert log == ["b", "a"]
