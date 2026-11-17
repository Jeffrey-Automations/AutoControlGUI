"""Revoke semantic worker authority using real stores and owned injected memory."""
from dataclasses import asdict, replace
from io import BytesIO

import pytest

from je_auto_control.utils.agent_runtime.context import current_operation, operation_scope
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.native_errors import error_reply
from je_auto_control.utils.agent_runtime.native_worker import NativeWorker
from je_auto_control.utils.agent_runtime.fixture_commands import FIXTURE_COMMAND
from je_auto_control.utils.executor.dispatch import dispatch_checkpoint
from je_auto_control.utils.process_memory.models import MemoryObservationError
from je_auto_control.utils.rbac.authorization import AuthorizationContext, authorization_scope
from je_auto_control.utils.rbac.users import UserStore
from je_auto_control.wrapper._input_observer import input_event
from headless.test_agent_fixture_readiness import spec
from headless.test_agent_fixture_target import setup


@pytest.fixture
def owned(tmp_path):
    target, _, channel, calls, provider, lease, watch = setup()
    store = UserStore(tmp_path / "private-users.json")
    store.add_user(user_id="alice", display_name="Alice", role="operator")
    owner = AuthorizationContext("alice", "operator", str(store.path))
    worker = NativeWorker(BytesIO(), BytesIO(), target=target)
    payload = {"spec": spec().to_dict(), "owner": asdict(owner)}
    try:
        yield worker, payload, store, provider, calls
    finally:
        worker._dispatch("cleanup", {"keys": [], "buttons": []})
        assert not calls or channel.retired
        assert not lease.pending_cleanup and not watch.pending_cleanup


@pytest.mark.parametrize("change", ["delete", "viewer", "admin", "missing", "damaged"])
@pytest.mark.parametrize("phase", ["configure", "observe", "read"])
def test_revoked_authority_stops_acquisition_reads_and_publication(owned, change, phase):
    worker, payload, store, provider, calls = owned

    def revoke():
        if change == "delete":
            store.remove_user("alice")
        elif change == "missing":
            store.path.unlink()
        elif change == "damaged":
            store.path.write_text("private invalid contents", encoding="utf-8")
        else:
            store.set_role("alice", change)

    if phase != "configure":
        assert worker._dispatch("configure", payload)["ready"]
    if phase == "read":
        provider.after_read = revoke
    else:
        revoke()
    with pytest.raises(AgentTaskError, match="authority") as caught:
        worker._dispatch("configure" if phase == "configure" else "observe", payload if phase == "configure" else {})
    assert len(provider.reads) == (1 if phase == "read" else 0)
    assert len(calls) == (0 if phase == "configure" else 1)
    reply = str(error_reply("request", caught.value))
    assert str(store.path) not in reply and "private invalid contents" not in reply


@pytest.mark.parametrize("change", ["owner", "spec", "target", "profile"])
def test_reader_callback_cannot_replace_worker_binding(owned, change):
    worker, payload, _, provider, _ = owned
    worker._dispatch("configure", payload)

    def mutate():
        if change == "owner":
            worker._owner = replace(worker._owner, store_path="other-store")
        elif change == "spec":
            worker._spec = replace(worker._spec, goal="another task")
        elif change == "target":
            worker._target = object()
        else:
            worker._profile_kind = "another-profile"

    original = worker._target
    provider.after_read = mutate
    try:
        with pytest.raises(AgentTaskError, match="configuration changed"):
            worker._dispatch("observe", {})
        assert len(provider.reads) == 1
    finally:
        worker._target = original


def test_nested_operation_cannot_use_original_checkpoint(owned):
    worker, payload, _, provider, _ = owned
    worker._dispatch("configure", payload)

    def replace_scope():
        operation = current_operation()
        with operation_scope(replace(operation)):
            operation.checkpoint()

    provider.after_read = replace_scope
    with pytest.raises(MemoryObservationError, match="target_changed"):
        worker._dispatch("observe", {})
    assert len(provider.reads) == 1


def test_store_provenance_cannot_change_between_requests(owned):
    worker, payload, _, provider, _ = owned
    worker._dispatch("configure", payload)
    replacement = payload | {"owner": payload["owner"] | {"store_path": "other-store"}}
    with pytest.raises(AgentTaskError, match="configuration is pinned"):
        worker._dispatch("configure", replacement)
    assert worker._dispatch("observe", {})["fields"]["document_id"] == 7
    assert provider.reads


@pytest.mark.parametrize("owner", [None, AuthorizationContext("local", "operator")])
def test_trusted_local_context_replaces_unrelated_ambient_role(owned, owner):
    worker, payload, _, _, _ = owned
    payload["owner"] = asdict(owner) if owner else {}
    with authorization_scope(AuthorizationContext("unrelated", "viewer")):
        assert worker._dispatch("configure", payload)["ready"]
        assert worker._dispatch("observe", {})["fields"]["document_id"] == 7


def test_revocation_after_target_returns_prevents_success_reply(owned):
    worker, payload, store, _, _ = owned
    original = worker._target.ready

    def ready(definition):
        result = original(definition)
        store.remove_user("alice")
        return result

    worker._target.ready = ready
    with pytest.raises(AgentTaskError, match="authority"):
        worker._dispatch("configure", payload)


def test_command_guard_uses_original_request_under_temporary_scope_replacement(owned):
    worker, payload, _, _, _ = owned
    original = worker._target.ready
    effects = []

    def ready(definition):
        result = original(definition)
        operation = current_operation()
        with operation_scope(replace(operation, checkpoint=lambda: None)):
            dispatch_checkpoint(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"})
            effects.append("executed")
        return result

    worker._target.ready = ready
    with pytest.raises(AgentTaskError, match="operation scope changed"):
        worker._dispatch("configure", payload)
    assert not effects


def test_activity_callback_revocation_prevents_target_access(owned):
    worker, payload, store, provider, _ = owned
    worker._dispatch("configure", payload)

    class Activity:
        def check(self):
            store.remove_user("alice")

    worker._activity = Activity()
    with pytest.raises(AgentTaskError, match="authority"):
        worker._dispatch("observe", {})
    assert not provider.reads


def test_revocation_after_command_effect_never_replays_or_publishes_receipt(owned):
    worker, payload, store, _, _ = owned
    worker._dispatch("configure", payload)
    observation = worker._dispatch("observe", {})
    channel = worker._target._owners.launcher._channel
    original = channel.request
    effects = []

    def exchange(*args, **kwargs):
        reply = original(*args, **kwargs)
        effects.append(reply)
        store.remove_user("alice")
        return reply

    channel.request = exchange
    request = {"tool": FIXTURE_COMMAND, "arguments": {"document_id": 42, "job_status": "done"},
               "expected": observation, "operation_id": "one-effect"}
    with pytest.raises(AgentTaskError, match="authority"):
        worker._dispatch("perform_grounded", request)
    store.add_user(user_id="alice", display_name="Alice", role="operator")
    with pytest.raises(AgentTaskError):
        worker._dispatch("perform_grounded", request)
    assert len(effects) == 1


@pytest.mark.parametrize("attempt", ["command", "input"])
def test_temporary_target_replacement_cannot_remove_semantic_guards(owned, attempt):
    worker, payload, _, _, _ = owned
    target = worker._target
    original = target.ready
    effects = []

    def ready(definition):
        result = original(definition)
        worker._target = object()
        try:
            if attempt == "command":
                dispatch_checkpoint(FIXTURE_COMMAND, {"document_id": 42, "job_status": "done"})
            else:
                input_event("key_press", keycode=65, is_shift=False)
            effects.append("executed")
        finally:
            worker._target = target
        return result

    target.ready = ready
    with pytest.raises(AgentTaskError, match="configuration changed|cannot emit desktop input"):
        worker._dispatch("configure", payload)
    assert not effects
