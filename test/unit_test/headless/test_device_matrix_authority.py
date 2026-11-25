"""Device-matrix workers run as the caller: its identity, guards, stop and cancellation."""
import threading
from concurrent.futures import CancelledError

import pytest

from je_auto_control.utils.device_matrix import run_on_devices
from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.executor.action_executor import Executor
from je_auto_control.utils.executor.dispatch import command_guard
from je_auto_control.utils.executor.run_control import ExecutionStopped, StopToken, stoppable_run
from je_auto_control.utils.mcp_server.context import OperationCancelledError
from je_auto_control.utils.rbac.authorization import (
    AuthorizationContext, authorization_scope, current_authorization,
)
from je_auto_control.utils.rbac.users import UserStore

#: A command no viewer may run; refused before its handler is reached.
PRIVILEGED = "AC_audit_log_list"
DEVICES = [{"platform": "desktop", "serial": "a"}, {"platform": "desktop", "serial": "b"}]


@pytest.fixture
def seen(monkeypatch):
    """Run ``Executor.execute_action`` as a recorder of who each worker runs as."""
    calls = []

    def record(_self, _actions, **_kwargs):
        calls.append(current_authorization())
        return {}
    monkeypatch.setattr(Executor, "execute_action", record)
    return calls


def test_workers_run_as_the_caller(seen):
    owner = AuthorizationContext("caller", "operator")
    with authorization_scope(owner):
        report = run_on_devices([["AC_set_var", {"name": "x", "value": 1}]], DEVICES)
    assert report.success
    assert seen == [owner, owner]
    assert current_authorization() is None


def test_a_privileged_command_is_refused_on_the_worker():
    viewer = AuthorizationContext("viewer", "viewer")
    with authorization_scope(viewer):
        report = run_on_devices([[PRIVILEGED]], DEVICES)
    assert report.passed == 0
    assert all("AuthorizationError" in result.error for result in report.results)


def test_a_removed_owner_is_refused_before_the_device_runs(tmp_path, seen):
    store = UserStore(tmp_path / "users.json")
    store.add_user(user_id="caller", display_name="Caller", role="operator")
    owner = AuthorizationContext("caller", "operator", store_path=str(store.path))
    store.remove_user("caller")
    with authorization_scope(owner):
        report = run_on_devices([], DEVICES)
    assert seen == []
    assert report.failed == 2
    assert "no longer authorised" in report.results[0].error


def test_a_damaged_user_store_fails_the_devices_not_the_matrix(tmp_path, seen):
    owner = AuthorizationContext("caller", "operator", store_path=str(tmp_path / "users.json"))
    (tmp_path / "users.json").mkdir()
    with authorization_scope(owner):
        report = run_on_devices([], DEVICES)
    assert seen == []
    assert report.failed == 2


def test_command_guards_reach_the_workers():
    def deny(name, _arguments):
        raise PermissionError(f"parent command ceiling for {name}")

    with command_guard(deny):
        report = run_on_devices([["AC_set_var", {"name": "x", "value": 1}]], DEVICES)
    assert report.passed == 0
    assert "parent command ceiling" in report.results[0].error


def test_a_stopped_run_is_not_a_device_failure():
    token = StopToken("matrix")
    ran = threading.Event()

    def stop(name, _arguments):
        ran.set()
        token.stop("test")

    body = [["AC_set_var", {"name": "x", "value": 1}]] * 3
    with stoppable_run(token=token), command_guard(stop), pytest.raises(ExecutionStopped):
        run_on_devices(body, DEVICES, max_parallel=1)
    assert ran.is_set()


def test_cancellation_reaches_the_workers():
    token = CancellationToken(1)

    def cancel(_name, _arguments):
        token.cancel()

    body = [["AC_set_var", {"name": "x", "value": 1}]] * 2
    with cancellation_scope(token), command_guard(cancel), pytest.raises(CancelledError):
        run_on_devices(body, DEVICES, max_parallel=1)


def test_an_mcp_cancellation_is_not_a_device_failure(monkeypatch):
    def cancelled(*_args, **_kwargs):
        raise OperationCancelledError(7)

    monkeypatch.setattr(Executor, "execute_action", cancelled)
    with pytest.raises(OperationCancelledError):
        run_on_devices([], DEVICES)
