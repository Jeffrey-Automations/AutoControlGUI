"""Exercise dual fixture sources with the real reader and injected owned native resources."""
from dataclasses import replace
import struct
import threading

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime
from je_auto_control.utils.agent_runtime.context import TaskOperation, operation_scope
from je_auto_control.utils.agent_runtime.errors import AgentObservationStale, AgentTaskError
from je_auto_control.utils.agent_runtime.fixture_commands import FIXTURE_COMMAND
from je_auto_control.utils.agent_runtime.fixture_observations import FIXTURE_SOURCES
from je_auto_control.utils.agent_runtime.observation_report import ObservationReport
from je_auto_control.utils.exception.control_signals import OperationCancelledError
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.process_memory.models import FailureReason, MemoryObservationError
from je_auto_control.utils.rbac.authorization import AuthorizationContext, authorization_scope
from je_auto_control.utils.rbac.users import UserStore
from headless.test_agent_fixture_readiness import spec
from headless.test_agent_fixture_target import setup


@pytest.fixture
def managed(tmp_path):
    target, _, channel, _, provider, *_ = setup()
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target})
    task = runtime.submit(spec()).task_id
    try:
        yield runtime, target, task, channel, provider
    finally:
        channel.fail_close = False
        runtime.close()


def act(runtime, task, frame):
    return runtime.act(task, {"tool": FIXTURE_COMMAND, "observation_id": frame.observation_id,
                             "arguments": {"document_id": 42, "job_status": "done"}})


@pytest.mark.parametrize("change", [{"document_id": 8}, {"job_status": "busy"}, {"sequence": 2}])
def test_source_disagreement_is_visible_and_never_reaches_compare_set(managed, change):
    runtime, _, task, channel, _ = managed
    original = channel.request
    commands = []

    def request(operation, payload, **kwargs):
        reply = original(operation, payload, **kwargs)
        if operation == "control":
            commands.append(payload["command"])
            return reply | change if payload["command"] == "snapshot" else reply
        return reply

    channel.request = request
    frame = runtime.observe(task)
    assert frame.data["status"] == "conflict"
    assert frame.data["sources"]["process_memory"]["snapshot"]["fields"]["document_id"] == 7
    with pytest.raises(AgentObservationStale):
        act(runtime, task, frame)
    assert "compare_set" not in commands and not runtime.store.actions(task)


def test_partial_memory_read_keeps_owned_ipc_state_without_authorizing_action(managed):
    runtime, _, task, channel, provider = managed
    original = provider.read
    provider.read = lambda address, size: original(address, size)[:-1] if size == 16 else original(address, size)
    frame = runtime.observe(task)
    assert frame.data["status"] == "partial"
    assert frame.data["sources"]["process_memory"] == {"failure": "partial_read"}
    assert frame.data["sources"]["fixture_protocol"]["snapshot"]["fields"] == {
        "document_id": 7, "job_status": "ready"}
    assert not channel.retired
    with pytest.raises(AgentObservationStale):
        act(runtime, task, frame)
    assert not runtime.store.actions(task)


@pytest.mark.parametrize("failure", [FailureReason.UNSUPPORTED, FailureReason.SCOPE_DENIED,
                                    FailureReason.TARGET_CHANGED, FailureReason.CLEANUP_FAILED])
def test_trust_and_ownership_failures_never_query_second_source(managed, failure):
    runtime, target, task, channel, _ = managed
    runtime.observe(task)
    original = channel.request
    called = []

    def request(operation, payload, **kwargs):
        called.append(operation)
        return original(operation, payload, **kwargs)

    def fail():
        raise MemoryObservationError(failure)

    channel.request = request
    target._target.observe = fail
    with pytest.raises(MemoryObservationError) as caught:
        runtime.observe(task)
    assert caught.value.reason is failure and not called


@pytest.mark.parametrize("change", [{"document_id": True}, {"sequence": True}, {"sequence": 3},
                                    {"extra": "private"}, {"job_status": "unknown"}])
def test_malformed_ipc_snapshot_retires_channel_without_partial_publication(managed, change):
    runtime, _, task, channel, _ = managed
    original = channel.request

    def request(operation, payload, **kwargs):
        reply = original(operation, payload, **kwargs)
        return reply | change if operation == "control" else reply

    channel.request = request
    with pytest.raises(AgentTaskError):
        runtime.observe(task)
    assert channel.retired and task not in runtime._observations


def test_ipc_protocol_error_preserves_failed_retirement_owner(managed):
    runtime, _, task, channel, _ = managed
    original = channel.request

    def request(operation, payload, **kwargs):
        if operation == "control":
            return {"malformed": True}
        return original(operation, payload, **kwargs)

    channel.request = request
    channel.fail_close = True
    with pytest.raises(AgentTaskError) as caught:
        runtime.observe(task)
    assert isinstance(caught.value.__cause__, AgentTaskError)
    assert not channel.retired and task not in runtime._observations


def test_completion_uses_both_new_sources_after_confirmed_command(managed):
    runtime, _, task, channel, _ = managed
    act(runtime, task, runtime.observe(task))
    original = channel.request

    def request(operation, payload, **kwargs):
        reply = original(operation, payload, **kwargs)
        return reply | {"job_status": "busy"} if payload.get("command") == "snapshot" else reply

    channel.request = request
    result = runtime.finish(task)
    assert result.state == "waiting_user" and result.verification == ({"kind": "semantic", "status": "unknown"},)
    assert len(runtime.store.actions(task)) == 1


def test_direct_commit_rechecks_both_sources_after_original_grounding(managed):
    runtime, target, task, channel, _ = managed
    frame = runtime.observe(task)
    expected = ObservationReport.from_dict(frame.data, required=FIXTURE_SOURCES).require_grounding()
    original = channel.request
    commands = []

    def request(operation, payload, **kwargs):
        commands.append(payload["command"])
        reply = original(operation, payload, **kwargs)
        return reply | {"sequence": 2} if payload["command"] == "snapshot" else reply

    channel.request = request
    with runtime._scope(runtime._row(task)), pytest.raises(AgentObservationStale):
        target.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                expected=expected, operation_id="direct")
    assert commands == ["snapshot"]


@pytest.mark.parametrize("adapter", ["fixture", "memory"])
def test_direct_commit_refuses_boolean_substitution_for_integer_state(managed, adapter):
    runtime, target, task, channel, provider = managed
    struct.pack_into("<I", provider.memory, 0x2300, 1)
    frame = runtime.observe(task)
    expected = ObservationReport.from_dict(frame.data, required=FIXTURE_SOURCES).require_grounding()
    forged = replace(expected, fields=(("document_id", True), ("job_status", "ready")))
    selected = target if adapter == "fixture" else target._target
    with runtime._scope(runtime._row(task)), pytest.raises(AgentObservationStale):
        selected.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                  expected=forged, operation_id="typed-state")
    assert struct.unpack_from("<I", provider.memory, 0x2300)[0] == 1 and not channel.retired


@pytest.mark.parametrize("fault", ["cancel", "scope"])
def test_source_boundary_rechecks_original_scope_and_preserves_cancellation(fault):
    target, _, channel, _, _, *_ = setup()
    requested = spec()
    ready = False
    replacement = None
    original = channel.request
    signal = OperationCancelledError("stop")

    def checkpoint():
        nonlocal replacement
        if ready:
            if fault == "cancel":
                raise signal
            replacement = operation_scope(TaskOperation(replace(requested, goal="other"), lambda: None, None))
            replacement.__enter__()

    def request(operation, payload, **kwargs):
        nonlocal ready
        result = original(operation, payload, **kwargs)
        if payload.get("command") == "snapshot":
            ready = True
        return result

    channel.request = request
    with operation_scope(TaskOperation(requested, checkpoint, None)):
        try:
            target.ready(requested)
            with pytest.raises(OperationCancelledError if fault == "cancel" else AgentTaskError) as caught:
                target.observe()
            if fault == "cancel":
                assert caught.value is signal
        finally:
            if replacement is not None:
                replacement.__exit__(None, None, None)
            target.cleanup()


def test_cleanup_interrupts_ipc_without_waiting_for_capture_lock():
    target, _, channel, _, _, *_ = setup()
    requested = spec()
    with operation_scope(TaskOperation(requested, lambda: None, None)):
        target.ready(requested)
    entered, retired = threading.Event(), threading.Event()
    original_request, original_close = channel.request, channel.close
    errors = []

    def request(operation, payload, **kwargs):
        if payload.get("command") == "snapshot":
            entered.set()
            if not retired.wait(5):
                raise RuntimeError("cleanup did not interrupt IPC")
        return original_request(operation, payload, **kwargs)

    def close():
        original_close()
        retired.set()

    def observe():
        with operation_scope(TaskOperation(requested, lambda: None, None)):
            try:
                target.observe()
            except AgentTaskError as error:
                errors.append(error)

    channel.request, channel.close = request, close
    worker = threading.Thread(target=observe)
    worker.start()
    try:
        assert entered.wait(5)
        target.cleanup()
    finally:
        retired.set()
        worker.join(5)
        target.cleanup()
    assert not worker.is_alive() and len(errors) == 1 and channel.retired


def test_store_revocation_after_memory_retirement_prevents_ipc_and_publication(tmp_path):
    target, _, channel, _, provider, *_ = setup()
    store = UserStore(tmp_path / "users.json")
    store.add_user(user_id="operator", display_name="Operator", role="admin")
    owner = AuthorizationContext("operator", "admin", store_path=str(store.path))
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target})
    close, request = provider.close, channel.request
    commands = []

    def revoke():
        close()
        store.remove_user("operator")

    def record(operation, payload, **kwargs):
        if operation == "control":
            commands.append(payload["command"])
        return request(operation, payload, **kwargs)

    provider.close, channel.request = revoke, record
    try:
        with authorization_scope(owner):
            task = runtime.submit(spec()).task_id
            with pytest.raises(AutoControlException):
                runtime.observe(task)
        assert not commands and task not in runtime._observations
    finally:
        runtime.close()


def test_capture_and_commit_cannot_interleave_sources_between_threads():
    target, _, channel, _, provider, *_ = setup()
    requested = spec()
    with operation_scope(TaskOperation(requested, lambda: None, None)):
        target.ready(requested)
        expected = ObservationReport.from_dict(target.observe(), required=FIXTURE_SOURCES).require_grounding()
    entered, release, action_started, action_done = (threading.Event() for _ in range(4))
    original = channel.request
    commands, errors = [], []

    def request(operation, payload, **kwargs):
        commands.append(payload["command"])
        if len(commands) == 1:
            entered.set()
            if not release.wait(5):
                raise RuntimeError("capture was not released")
        return original(operation, payload, **kwargs)

    def capture():
        with operation_scope(TaskOperation(requested, lambda: None, None)):
            try:
                target.observe()
            except AutoControlException as error:
                errors.append(error)

    def commit():
        with operation_scope(TaskOperation(requested, lambda: None, None)):
            action_started.set()
            try:
                target.perform_grounded(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"},
                                        expected=expected, operation_id="serialized")
            except AutoControlException as error:
                errors.append(error)
            finally:
                action_done.set()

    channel.request = request
    reader, writer = threading.Thread(target=capture), threading.Thread(target=commit)
    reader.start()
    try:
        assert entered.wait(5)
        reads = len(provider.reads)
        writer.start()
        assert action_started.wait(5)
        assert not action_done.wait(0.1) and len(provider.reads) == reads
    finally:
        release.set()
        reader.join(5)
        if writer.ident is not None:
            writer.join(5)
        target.cleanup()
    assert not reader.is_alive() and not writer.is_alive() and not errors
    assert commands == ["snapshot", "snapshot", "compare_set"]
