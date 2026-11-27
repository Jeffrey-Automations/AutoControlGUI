"""Round-3 regression: AgentLoop._dispatch_tool must record AutoControl*
exceptions and TypeErrors per-step (loop continues) instead of crashing the
whole run."""
from concurrent.futures import CancelledError

import pytest

from je_auto_control.utils.agent import AgentBackend, AgentLoop, FakeAgentBackend
from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.exception.control_signals import OperationCancelledError
from je_auto_control.utils.exception.exceptions import AutoControlMouseException
from je_auto_control.utils.executor.run_control import (
    ExecutionStopped, StopToken, checkpoint, stoppable_run,
)


def _run_with_failing_runner(exc):
    def runner(_name, _args):
        raise exc

    backend = FakeAgentBackend([
        {"tool": "AC_click_mouse", "input": {"button": "left"}},
        {"stop": True, "message": "done"},
    ])
    return AgentLoop(
        backend, tool_runner=runner, screenshot_fn=lambda: None,
    ).run("goal")


def test_autocontrol_exception_recorded_and_loop_continues():
    result = _run_with_failing_runner(AutoControlMouseException("boom"))
    failing = next(s for s in result.steps if s.tool == "AC_click_mouse")
    assert failing.error is not None
    assert "AutoControlMouseException" in failing.error
    # The loop kept going to the stop decision rather than aborting the run.
    assert result.succeeded is True
    assert result.final_message == "done"


def test_type_error_from_hallucinated_kwarg_recorded_and_loop_continues():
    result = _run_with_failing_runner(
        TypeError("unexpected keyword argument 'foo'"),
    )
    failing = next(s for s in result.steps if s.tool == "AC_click_mouse")
    assert failing.error is not None
    assert "TypeError" in failing.error
    assert result.succeeded is True


def _asks_for_ever(asked):
    class Backend(AgentBackend):
        def decide_next_action(self, goal, screenshot, history):
            asked.append(len(history))
            return {"tool": "AC_click_mouse", "input": {}}
    return Backend()


def test_a_stopped_run_ends_the_loop_instead_of_asking_the_model_again():
    """ExecutionStopped was recorded as a failed step: the model was asked max_steps times more."""
    token, asked = StopToken("agent-loop"), []

    def runner(_name, _args):
        token.stop("test")
        checkpoint()

    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        AgentLoop(_asks_for_ever(asked), tool_runner=runner, screenshot_fn=lambda: None).run("goal")
    assert len(asked) == 1


def test_a_stop_between_steps_is_seen_before_the_model_is_asked():
    token, asked = StopToken("agent-loop"), []
    with stoppable_run(token=token), pytest.raises(ExecutionStopped):
        AgentLoop(_asks_for_ever(asked), tool_runner=lambda _n, _a: token.stop("test"),
                  screenshot_fn=lambda: None).run("goal")
    assert len(asked) == 1


def test_cancellation_ends_the_loop():
    token, asked = CancellationToken(1), []
    with cancellation_scope(token), pytest.raises(CancelledError):
        AgentLoop(_asks_for_ever(asked), tool_runner=lambda _n, _a: token.cancel(),
                  screenshot_fn=lambda: None).run("goal")
    assert len(asked) == 1


def test_an_mcp_cancellation_is_not_a_failed_step():
    with pytest.raises(OperationCancelledError):
        _run_with_failing_runner(OperationCancelledError(3))
