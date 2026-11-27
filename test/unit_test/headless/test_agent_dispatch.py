"""Agent tools must share executor authorization, cancellation and capture."""
from unittest.mock import patch

import pytest

from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.rbac.authorization import AuthorizationContext, authorization_scope
from je_auto_control.utils.rbac.authorization import AuthorizationError
from je_auto_control.utils.tool_use_schema import run_tool_call


def test_agent_tool_cannot_bypass_viewer_authority():
    calls = []
    with patch("je_auto_control.utils.executor.action_executor.executor.event_dict",
               {"AC_click_mouse": lambda: calls.append(True)}):
        with authorization_scope(AuthorizationContext("reader", "viewer")):
            with pytest.raises(AuthorizationError):
                run_tool_call("AC_click_mouse", {})
    assert calls == []


def test_cancelled_tool_never_calls_handler():
    from concurrent.futures import CancelledError
    token = CancellationToken(1)
    token.cancel()
    calls = []
    with patch("je_auto_control.utils.executor.action_executor.executor.event_dict",
               {"AC_noop": lambda: calls.append(True)}):
        with cancellation_scope(token), pytest.raises(CancelledError):
            run_tool_call("AC_noop", {})
    assert calls == []


def test_tool_rejects_private_executor_arguments():
    with patch("je_auto_control.utils.executor.action_executor.executor.event_dict",
               {"AC_execute_action": lambda **kwargs: None}):
        with pytest.raises(ValueError, match="private"):
            run_tool_call("AC_execute_action", {"action_list": [], "_validated": True})


def test_single_dispatch_returns_raw_value_and_interpolates():
    from je_auto_control.utils.executor.action_executor import Executor
    executor = Executor()
    executor.event_dict = {"AC_echo": lambda value: {"value": value}}
    executor.variables.set("answer", 42)
    assert executor.execute_one("AC_echo", {"value": "${answer}"}) == {"value": 42}


def test_single_dispatch_restores_executor_and_strictness():
    from je_auto_control.utils.executor.action_executor import Executor, _RUNNING, _STRICT_BODIES
    previous = getattr(_RUNNING, "value", None)
    executor = Executor()
    executor.event_dict = {"AC_fail": lambda: (_ for _ in ()).throw(ValueError("failure"))}
    with pytest.raises(ValueError, match="failure"):
        executor.execute_one("AC_fail", {})
    assert getattr(_RUNNING, "value", None) is previous
    assert not getattr(_STRICT_BODIES, "value", False)


def test_task_guard_survives_parallel_worker_boundary():
    from je_auto_control.utils.executor.action_executor import Executor
    from je_auto_control.utils.executor.dispatch import command_guard
    from je_auto_control.utils.exception.exceptions import AutoControlException
    executor = Executor()
    calls = []
    executor.event_dict["AC_forbidden_test"] = lambda: calls.append(True)

    def guard(name, _arguments):
        if name == "AC_forbidden_test":
            raise AutoControlException("task guard refused child")

    with command_guard(guard), pytest.raises(AutoControlException, match="refused"):
        executor.execute_one("AC_parallel", {"branches": [[["AC_forbidden_test"]]]})
    assert calls == []


@pytest.mark.parametrize("name", ["AC_break", "AC_continue"])
def test_single_dispatch_of_a_loop_signal_is_a_framework_error(name):
    from je_auto_control.utils.exception.exceptions import AutoControlActionException
    from je_auto_control.utils.executor.action_executor import Executor
    with pytest.raises(AutoControlActionException, match="outside a loop"):
        Executor().execute_one(name)


# --- an agent payload is expanded once, by the runtime -----------------------

_FETCHED = "${secrets.PRIVATE}"   # text a flow read from OCR, HTTP or a file


def _payload_capture():
    received = []

    def submit(spec, idempotency_key=None):
        received.append(spec)

    def lookup(idempotency_key, spec=None):
        received.append(spec)

    def act(task_id, action):
        received.append(action)

    def manage(operation, request=None):
        received.append(request)
    return received, {"AC_agent_task_submit": submit, "AC_agent_task_lookup": lookup,
                      "AC_agent_task_act": act, "AC_agent_dag": manage, "AC_agent_trigger": manage,
                      "AC_agent_skill": manage, "AC_agent_task_recovery": manage}


@pytest.mark.parametrize("command, arguments, payload", [
    ("AC_agent_task_submit", "spec", {"actions": [{"tool": "AC_type_keyboard", "arguments": {"text": "${fetched}"}}],
                                      "success_criteria": [{"kind": "file_exists", "path": "${event.key}.json"}]}),
    ("AC_agent_task_lookup", "spec", {"actions": [{"tool": "AC_type_keyboard", "arguments": {"text": "${fetched}"}}]}),
    ("AC_agent_task_act", "action", {"tool": "AC_type_keyboard", "arguments": {"text": "${fetched}"}}),
    ("AC_agent_dag", "request", {"nodes": [{"spec": {"inputs": {"text": "${fetched}"}}}]}),
    ("AC_agent_trigger", "request", {"spec": {"inputs": {"text": "${fetched}"}}}),
    ("AC_agent_skill", "request", {"spec": {"inputs": {"text": "${fetched}"}}}),
    ("AC_agent_task_recovery", "request", {"spec": {"inputs": {"text": "${fetched}"}}}),
])
def test_an_agent_payload_reaches_the_runtime_unexpanded(command, arguments, payload, monkeypatch):
    """The runtime expands a task's placeholders against its own inputs, when each action runs.

    Expanded at dispatch as well, a variable holding fetched text that
    contained ``${secrets.NAME}`` was resolved on the second pass, and a
    placeholder meant for the task's inputs (``${event.key}``) was refused
    at dispatch as an unknown variable.
    """
    from je_auto_control.utils.executor.action_executor import Executor
    from je_auto_control.utils.secrets import default_secret_manager
    vault = []
    monkeypatch.setattr(default_secret_manager, "get", lambda name: vault.append(name) or "private")
    received, handlers = _payload_capture()
    executor = Executor()
    executor.event_dict = handlers
    executor.variables.set("fetched", _FETCHED)
    named = {"task_id": "t1", "operation": "register", "idempotency_key": "k1", arguments: payload}
    signature = {"AC_agent_task_submit": ("spec",), "AC_agent_task_lookup": ("idempotency_key", "spec"),
                 "AC_agent_task_act": ("task_id", "action")}.get(command, ("operation", "request"))
    executor.execute_one(command, {name: named[name] for name in signature})
    executor._execute_event([command, [named[name] for name in signature]])   # positional as well
    assert received == [payload, payload]
    assert vault == []
