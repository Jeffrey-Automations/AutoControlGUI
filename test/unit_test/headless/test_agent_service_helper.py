"""Verify the service-only IPC boundary with actual hidden Python helper retirement."""
from dataclasses import asdict, replace
from concurrent.futures import CancelledError
from io import BytesIO
from pathlib import Path
import sys
import threading
import time

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime.models import AgentTaskBudget
from je_auto_control.utils.agent_runtime.context import TaskOperation, operation_scope
from je_auto_control.utils.agent_runtime.errors import AgentControlBusy, AgentEffectUnknown, AgentTaskError
from je_auto_control.utils.agent_runtime.native_channel import classify_reply
from je_auto_control.utils.agent_runtime.native_errors import error_reply
from je_auto_control.utils.agent_runtime.native_worker import NativeWorker
from je_auto_control.utils.agent_runtime.service_native_target import NativeServiceTarget
from je_auto_control.utils.agent_runtime.service_operations import ServiceOperation
from je_auto_control.utils.agent_runtime.service_scope import service_scope
from je_auto_control.utils.agent_runtime.service_status import ServiceFailure, ServiceQueryError
from je_auto_control.utils.agent_runtime.service_target import ManagedServiceTarget
from je_auto_control.utils.rbac.authorization import AuthorizationContext
from je_auto_control.utils.rbac.users import UserStore
from je_auto_control.wrapper._input_observer import input_event
from headless.test_agent_service_control import ControlApi

HELPER = Path(__file__).resolve().parents[2] / "fixtures" / "service_helper.py"


def spec(target="service", tool="AC_service_start", seconds=3):
    return AgentTaskSpec(goal="verify service report", target=target, allowed_tools=(tool,),
        success_criteria=({"kind": "service_state", "tool": tool,
                           "state": "running" if tool.endswith("start") else "stopped"},),
        budget=AgentTaskBudget(action_seconds=seconds))


def proxy(tmp_path, *, target="service", key="OwnedFixture", digest="a" * 64,
          fault="none", initial=1, marker=None):
    argv = [sys.executable, "-u", str(HELPER), fault, target, key, digest, str(initial)]
    if marker is not None:
        argv.append(str(marker))
    return NativeServiceTarget(argv=argv, service_key=key, target_id=target, config_digest=digest,
                               lock_root=tmp_path / "locks")


@pytest.mark.parametrize("tool,initial", [("AC_service_start", 1), ("AC_service_stop", 4)])
@pytest.mark.parametrize("fault,status", [("none", "passed"), ("no_effect", "failed")])
def test_hidden_helper_reads_controls_and_verifies(tmp_path, tool, initial, fault, status):
    target = proxy(tmp_path, fault=fault, initial=initial)
    runtime = AgentRuntime(tmp_path / "runtime.db", targets={"service": target})
    try:
        task = runtime.submit(spec(tool=tool)).task_id
        frame = runtime.observe(task)
        channel = target._channel
        assert frame.data["binding_id"] == target.service_binding.binding_id
        result = runtime.act(task, {"tool": tool, "observation_id": frame.observation_id})
        assert result.result["accepted"] is True and result.result["comparison"] == "non_atomic"
        finished = runtime.finish(task)
        assert finished.verification == ({"kind": "service_state", "status": status},)
        assert target._ledger.empty
    finally:
        runtime.close()
    assert channel.retired and channel._process.poll() is not None


@pytest.mark.parametrize("fault", ["lose_reply", "input"])
def test_unknown_effect_never_replays(tmp_path, fault):
    target = proxy(tmp_path, fault=fault)
    runtime = AgentRuntime(tmp_path / "runtime.db", targets={"service": target})
    try:
        task = runtime.submit(spec()).task_id
        frame = runtime.observe(task)
        channel = target._channel
        with pytest.raises(AgentEffectUnknown):
            runtime.act(task, {"tool": "AC_service_start", "observation_id": frame.observation_id})
        assert runtime.store.actions(task)[0]["status"] == "uncertain"
        with pytest.raises(AgentTaskError):
            runtime.act(task, {"tool": "AC_service_start", "observation_id": frame.observation_id})
        assert target._ledger.empty
    finally:
        runtime.close()
    assert channel.retired


@pytest.mark.parametrize("fault", ["stale", "binding", "malformed", "query_denied"])
def test_invalid_source_never_publishes(tmp_path, fault):
    target = proxy(tmp_path, fault=fault)
    runtime = AgentRuntime(tmp_path / "runtime.db", targets={"service": target})
    try:
        task = runtime.submit(spec()).task_id
        with pytest.raises(AgentTaskError) as error:
            runtime.observe(task)
        if fault == "query_denied":
            assert isinstance(error.value, ServiceQueryError)
            assert error.value.reason is ServiceFailure.ACCESS_DENIED
    finally:
        runtime.close()


def worker(allowed=frozenset(ServiceOperation)):
    api = ControlApi()
    api.state = 1
    target = ManagedServiceTarget("service", "a" * 64, service_scope("OwnedFixture"), api.controller(),
                                  allowed=allowed)
    value = NativeWorker(BytesIO(), BytesIO(), target=target)
    return value, target, api


@pytest.mark.parametrize("change", ["profile", "presence", "target", "tools", "mode", "apps", "owner_type"])
def test_configuration_preflight_preserves_original_state(change):
    value, _, api = worker(frozenset({ServiceOperation.START}))
    payload = {"spec": spec().to_dict(), "owner": {}}
    if change in {"profile", "presence"}:
        payload[change] = {}
    elif change == "owner_type":
        payload["owner"] = False
    else:
        key, item = {"target": ("target", "other"), "tools": ("allowed_tools", ["AC_service_stop"]),
                     "mode": ("mode", "plan"), "apps": ("apps", ["anything"])}[change]
        payload["spec"][key] = item
    with pytest.raises(AgentTaskError):
        value._dispatch("configure", payload)
    assert value._spec is None and value._owner is None and not api.OpenSCManagerW.calls
    value.close()


def test_worker_scope_is_pinned_and_legacy_operations_refused():
    value, _, api = worker()
    payload = {"spec": spec().to_dict(), "owner": {}}
    assert value._dispatch("configure", payload)["ready"]
    with pytest.raises(AgentTaskError):
        value._dispatch("configure", {"spec": replace(spec(), goal="changed").to_dict(), "owner": {}})
    for operation in ("perform", "perform_grounded"):
        with pytest.raises(AgentTaskError):
            value._dispatch(operation, {"tool": "AC_service_start", "arguments": {}})
    with pytest.raises(AgentTaskError):
        value._dispatch("cleanup", {"keys": [{"keycode": 65}], "buttons": []})
    assert not api.OpenSCManagerW.calls
    value.close()


@pytest.mark.parametrize("phase", ["request", "cleanup", "eof"])
@pytest.mark.parametrize("kind", ["input", "command"])
def test_worker_guards_every_resource_phase(phase, kind):
    from je_auto_control.utils.executor.dispatch import dispatch_checkpoint
    value, target, _ = worker()
    value._dispatch("configure", {"spec": spec().to_dict(), "owner": {}})

    def attempt():
        if kind == "input":
            input_event({"kind": "key_release", "keycode": 65, "is_shift": False})
        else:
            dispatch_checkpoint("AC_write", {"text": "blocked"})

    if phase == "request":
        target.observe = attempt
    else:
        target.cleanup = attempt
    with pytest.raises(AgentTaskError):
        if phase == "request":
            value._dispatch("observe", {})
        elif phase == "eof":
            value.close()
        else:
            value._dispatch("cleanup", {"keys": [], "buttons": []})
    assert not value._sink.getvalue()


@pytest.mark.parametrize("phase", ["configure", "observe", "read"])
def test_worker_rechecks_live_authority(tmp_path, phase):
    value, _, api = worker()
    users = UserStore(tmp_path / "users.json")
    users.add_user(user_id="alice", display_name="Alice", role="operator")
    owner = AuthorizationContext("alice", "operator", str(users.path))
    payload = {"spec": spec().to_dict(), "owner": asdict(owner)}
    if phase != "configure":
        value._dispatch("configure", payload)
    if phase == "read":
        original = api.QueryServiceStatusEx.call
        def query(*args):
            result = original(*args)
            users.remove_user("alice")
            return result
        api.QueryServiceStatusEx.call = query
    else:
        users.remove_user("alice")
    with pytest.raises(AgentTaskError, match="authority"):
        value._dispatch("configure" if phase == "configure" else "observe", payload if phase == "configure" else {})
    value.close()


@pytest.mark.parametrize("change", ["target", "operation"])
def test_worker_checkpoint_rejects_replaced_context(change):
    from je_auto_control.utils.agent_runtime import context
    value, target, api = worker()
    value._dispatch("configure", {"spec": spec().to_dict(), "owner": {}})

    def replace_context():
        if change == "target":
            value._target = object()
        else:
            context._CURRENT.set(TaskOperation(spec(), lambda: None, None))

    value._check_activity = replace_context
    with pytest.raises(AgentTaskError, match="changed"):
        value._dispatch("observe", {})
    assert not api.OpenSCManagerW.calls
    value._target = target
    value.close()


@pytest.mark.parametrize("reason", list(ServiceFailure))
def test_service_error_protocol_keeps_closed_reason(reason):
    reply = error_reply("id", ServiceQueryError(reason))
    with pytest.raises(ServiceQueryError) as error:
        classify_reply(reply, "id")
    assert error.value.reason is reason


@pytest.mark.parametrize("change", [{"service_reason": "private-value"}, {"error": "private-message"},
    {"event": {}}, {"memory_reason": "access_denied"}, {"extra": True}, {"error_type": "MemoryObservationError"}])
def test_malformed_service_failures_cannot_be_events_or_echo_text(change):
    reply = error_reply("id", ServiceQueryError(ServiceFailure.UNAVAILABLE)) | change
    with pytest.raises(AgentTaskError) as error:
        classify_reply(reply, "id")
    assert "private" not in str(error.value)


def test_service_reason_only_packet_cannot_be_an_event():
    with pytest.raises(AgentTaskError, match="invalid service failure"):
        classify_reply({"id": "id", "event": {}, "service_reason": "private"}, "id")


@pytest.mark.parametrize("kind", [[], {}, ["ServiceQueryError"]])
def test_non_string_error_type_cannot_escape_typed_failure_validation(kind):
    with pytest.raises(AgentTaskError, match="invalid service failure"):
        classify_reply({"id": "id", "event": {}, "service_reason": "private", "error_type": kind}, "id")


@pytest.mark.parametrize("owner", [
    {"user_id": [], "role": "operator", "store_path": None},
    {"user_id": "alice", "role": {}, "store_path": None},
    {"user_id": "alice", "role": "operator", "store_path": 5},
    {"user_id": "", "role": "operator", "store_path": None},
])
def test_invalid_owner_does_not_poison_configuration(owner):
    value, _, api = worker()
    with pytest.raises(AgentTaskError, match="invalid owner"):
        value._dispatch("configure", {"spec": spec().to_dict(), "owner": owner})
    assert value._spec is None and value._owner is None
    assert value._dispatch("configure", {"spec": spec().to_dict(), "owner": {}})["ready"]
    assert not api.OpenSCManagerW.calls
    value.close()


def test_bootstrap_is_inert_and_proxy_rejects_list_arguments(tmp_path):
    value, target, api = worker()
    packet = value._dispatch("bootstrap", {})
    client = proxy(tmp_path)
    assert client._supports_bootstrap(packet)
    assert not api.OpenSCManagerW.calls
    value._dispatch("configure", {"spec": spec().to_dict(), "owner": {}})
    observed = value._dispatch("observe", {})
    with pytest.raises(AgentTaskError):
        client.perform_observed("AC_service_start", [], observation=observed, operation_id="operation")
    assert client._channel is None
    target.cleanup()


def test_unconfirmed_cleanup_keeps_channel_for_retry(tmp_path):
    target = proxy(tmp_path)

    class Channel:
        retired = False
        reply = {"cleaned": False}

        def request(self, *_args, **_kwargs):
            return self.reply

        def close(self):
            self.retired = True

    channel = Channel()
    target._channel = channel
    with pytest.raises(AgentTaskError, match="unconfirmed"):
        target.cleanup()
    assert target._channel is channel and not channel.retired
    channel.reply = {"cleaned": True}
    target.cleanup()
    assert target._channel is None and channel.retired


@pytest.mark.parametrize("change", [{"target_id": "other"}, {"config_digest": "b" * 64},
                                   {"scope_id": "other"}, {"version": True}, {"binding_id": ""}])
def test_proxy_refuses_wrong_bootstrap(tmp_path, change):
    target = proxy(tmp_path)
    binding = {"version": 1, "target_id": "service", "config_digest": "a" * 64,
               "scope_id": service_scope("OwnedFixture"), "binding_id": "original"}
    assert not target._supports_bootstrap({"protocol": 1, "service": binding | change})
    assert target._channel is None


def test_proxy_never_rebinds_after_restart(tmp_path):
    target = proxy(tmp_path)
    binding = {"version": 1, "target_id": "service", "config_digest": "a" * 64,
               "scope_id": service_scope("OwnedFixture"), "binding_id": "original"}
    assert target._supports_bootstrap({"protocol": 1, "service": binding})
    assert not target._supports_bootstrap({"protocol": 1, "service": binding | {"binding_id": "replacement"}})


@pytest.mark.parametrize("key", ["非ASCII", "bad/name", "bad\\name", "x\0y", "", "x" * 257])
def test_unsupported_keys_fail_before_helper_launch(tmp_path, key):
    with pytest.raises(ServiceQueryError, match="unsupported"):
        proxy(tmp_path, key=key)


def test_same_service_serializes_distinct_targets_and_databases(tmp_path):
    first, second = proxy(tmp_path), proxy(tmp_path, target="another", key="OWNEDFIXTURE", digest="b" * 64)
    assert first._resource_path == second._resource_path
    one = AgentRuntime(tmp_path / "one.db", targets={"service": first})
    two = AgentRuntime(tmp_path / "two.db", targets={"another": second})
    try:
        task = one.submit(spec()).task_id
        one.observe(task)
        with pytest.raises(AgentControlBusy):
            two.observe(two.submit(spec("another")).task_id)
        assert second._channel is None
        one.cancel(task)
        with operation_scope(TaskOperation(spec("another"), lambda: None, None)):
            assert second.ready(spec("another"))[0]
            assert second.observe()["target_id"] == "another"
            second_channel = second._channel
    finally:
        one.close()
        two.close()
        second.cleanup()
    assert second_channel.retired and second_channel._process.poll() is not None


def test_cancel_retires_blocked_control_process(tmp_path):
    marker = tmp_path / "entered.txt"
    target = proxy(tmp_path, fault="hang", marker=marker)
    runtime = AgentRuntime(tmp_path / "runtime.db", targets={"service": target})
    errors = []
    thread = None
    try:
        task = runtime.submit(spec(seconds=20)).task_id
        frame = runtime.observe(task)
        channel = target._channel
        def blocked():
            try:
                runtime.act(task, {"tool": "AC_service_start", "observation_id": frame.observation_id})
            except (AgentTaskError, CancelledError) as error:
                errors.append(error)
        thread = threading.Thread(target=blocked)
        thread.start()
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        assert marker.read_text() == "entered"
        runtime.cancel(task)
        thread.join(5)
        assert not thread.is_alive() and errors
        assert channel.retired and channel._process.poll() is not None
        assert runtime.store.actions(task)[0]["status"] == "uncertain"
    finally:
        runtime.close()
        if thread is not None:
            thread.join(5)


def test_action_deadline_retires_blocked_helper(tmp_path):
    target = proxy(tmp_path, fault="hang")
    runtime = AgentRuntime(tmp_path / "deadline.db", targets={"service": target})
    try:
        task = runtime.submit(spec(seconds=1)).task_id
        frame = runtime.observe(task)
        channel = target._channel
        with pytest.raises(AgentTaskError):
            runtime.act(task, {"tool": "AC_service_start", "observation_id": frame.observation_id})
        assert runtime.store.actions(task)[0]["status"] == "uncertain"
        assert channel.retired and channel._process.poll() is not None
    finally:
        runtime.close()


def test_helper_crash_after_effect_keeps_journal_uncertain(tmp_path):
    marker = tmp_path / "effect.txt"
    target = proxy(tmp_path, fault="crash_after_effect", marker=marker)
    runtime = AgentRuntime(tmp_path / "crash.db", targets={"service": target})
    try:
        task = runtime.submit(spec()).task_id
        frame = runtime.observe(task)
        channel = target._channel
        with pytest.raises(AgentTaskError):
            runtime.act(task, {"tool": "AC_service_start", "observation_id": frame.observation_id})
        assert marker.read_text() == "effect"
        assert runtime.store.actions(task)[0]["status"] == "uncertain"
        with pytest.raises(AgentTaskError):
            runtime.act(task, {"tool": "AC_service_start", "observation_id": frame.observation_id})
        assert len(runtime.store.actions(task)) == 1
        assert channel.retired and channel._process.poll() is not None
    finally:
        runtime.close()


def test_replacement_helper_cannot_complete_an_old_acceptance(tmp_path):
    database = tmp_path / "restart.db"
    first = proxy(tmp_path)
    runtime = AgentRuntime(database, targets={"service": first})
    try:
        task = runtime.submit(spec()).task_id
        frame = runtime.observe(task)
        runtime.act(task, {"tool": "AC_service_start", "observation_id": frame.observation_id})
        original = first.service_binding
        runtime.pause(task)
    finally:
        runtime.close()
    second = proxy(tmp_path, initial=4)
    restored = AgentRuntime(database, targets={"service": second})
    try:
        restored.resume(task)
        result = restored.finish(task)
        assert second.service_binding != original
        assert result.verification == ({"kind": "service_state", "status": "unknown"},)
        assert result.state == "waiting_user"
        assert len(restored.store.actions(task)) == 1
    finally:
        restored.close()
