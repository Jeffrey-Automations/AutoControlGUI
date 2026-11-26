"""Managed batches pin the whole graph and claim before any possible task delivery."""
import pytest
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import Mock

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskError
from je_auto_control.utils.rbac.authorization import AuthorizationContext, AuthorizationError, authorization_scope
from je_auto_control.utils.dag import managed_tasks
from je_auto_control.utils.dag import DagDefinitionError
from .test_dag_managed_tasks import task


def graph():
    return {"nodes": [{"id": "a", "task": task(idempotency_key="a")},
                      {"id": "b", "depends_on": ["a"], "task": task(idempotency_key="b")}]}


@pytest.fixture
def runtime(tmp_path):
    instance = AgentRuntime(tmp_path / "agent_runtime.sqlite", targets={"fixture": object()})
    try:
        yield instance
    finally:
        instance.close()


def test_registered_batch_is_durable_and_does_not_dispatch(runtime):
    value = runtime.batches.control("register", {"definition": graph()})
    assert value["state"] == "registered"
    assert runtime.list() == []
    assert value["definition"]["nodes"][1]["depends_on"] == ["a"]
    assert value["resume_permitted"] is False
    assert runtime.batches.control("get", {"batch_id": value["batch_id"]}) == value


def test_claim_is_durable_and_never_reissued_after_an_unknown_submission(runtime):
    value = runtime.batches.control("register", {"definition": graph()})
    started = runtime.batches.control("begin", {"batch_id": value["batch_id"],
                                               "definition": graph(), "max_parallel": 4})
    request = {"batch_id": value["batch_id"], "attempt": started["attempt"], "node_id": "a"}
    runtime.batches.control("claim", request)
    with pytest.raises(AgentTaskError):
        runtime.batches.control("claim", request)
    with pytest.raises(AgentTaskError):
        runtime.batches.control("claim", {**request, "node_id": "b"})
    assert runtime.batches.control("get", {"batch_id": value["batch_id"]})["nodes"][0]["phase"] == "claimed"


def test_changed_topology_cannot_begin_a_registered_batch(runtime):
    value = runtime.batches.control("register", {"definition": graph()})
    changed = graph()
    changed["nodes"][1]["depends_on"] = []
    with pytest.raises(AgentTaskError, match="graph"):
        runtime.batches.control("begin", {"batch_id": value["batch_id"], "definition": changed, "max_parallel": 4})


@pytest.mark.parametrize("change", ["host", "task", "key", "node", "parallel"])
def test_all_graph_fields_and_parallelism_are_bound_before_execution(runtime, change):
    value = runtime.batches.control("register", {"definition": graph()})
    changed, parallel = graph(), 4
    if change == "host":
        changed["nodes"][0]["host"] = "not-registered"
    elif change == "task":
        changed["nodes"][0]["task"]["spec"]["goal"] = "changed"
    elif change == "key":
        changed["nodes"][0]["task"]["idempotency_key"] = "changed"
    elif change == "node":
        changed["nodes"].pop()
    else:
        parallel = 2
    with pytest.raises((AgentTaskError, AuthorizationError)):
        runtime.batches.control("begin", {"batch_id": value["batch_id"], "definition": changed,
                                           "max_parallel": parallel})
    assert runtime.batches.control("get", {"batch_id": value["batch_id"]})["state"] == "registered"


@pytest.mark.parametrize("fault", ["differs", "wrong_id", "bad_version", "incomplete", "held_input", "diagnostic"])
def test_claimed_completion_requires_exact_destination_binding_and_retirement(runtime, monkeypatch, fault):
    value = runtime.batches.control("register", {"definition": graph()})
    started = runtime.batches.control("begin", {"batch_id": value["batch_id"],
                                               "definition": graph(), "max_parallel": 4})
    request = {"batch_id": value["batch_id"], "attempt": started["attempt"], "node_id": "a"}
    runtime.batches.control("claim", request)
    reply = {"found": True, "spec_match_contract": 1, "spec_match": "matches", "task": {
        "task_id": "accepted-a", "state": "succeeded", "metadata": {"completion_contract": 1, "input_released": True},
        "verification": [{"kind": "result_equals", "status": "passed"}]}}
    if fault == "differs":
        reply["spec_match"] = "differs"
    elif fault == "wrong_id":
        reply["task"]["task_id"] = "unrelated"
    elif fault == "bad_version":
        reply["spec_match_contract"] = True
    elif fault == "incomplete":
        reply["task"]["verification"] = []
    elif fault == "held_input":
        reply["task"]["metadata"]["input_released"] = False
    endpoint = Mock(return_value=reply)
    if fault == "diagnostic":
        endpoint.side_effect = AgentTaskError("private-token-from-fixture")
    monkeypatch.setattr(managed_tasks, "bound_task_connection", lambda *_args: endpoint)
    with pytest.raises(AgentTaskError) as error:
        runtime.batches.control("record", {**request, "receipt": {"outcome": "completed", "task_id": "accepted-a"}})
    assert "private-token" not in str(error.value)
    current = runtime.batches.control("get", {"batch_id": value["batch_id"]})
    assert current["nodes"][0]["phase"] == "claimed"


def test_owner_and_drive_permission_are_required_without_leaking_other_batches(runtime):
    with authorization_scope(AuthorizationContext("alice", "operator")):
        value = runtime.batches.control("register", {"definition": graph()})
    with authorization_scope(AuthorizationContext("bob", "operator")):
        assert runtime.batches.control("list")["batches"] == []
        with pytest.raises(AgentTaskError, match="another caller"):
            runtime.batches.control("get", {"batch_id": value["batch_id"]})
    with authorization_scope(AuthorizationContext("alice", "viewer")):
        with pytest.raises(AuthorizationError):
            runtime.batches.control("get", {"batch_id": value["batch_id"]})


def test_atomic_registration_rolls_back_graph_and_nodes(runtime):
    with runtime.store.connection(write=True) as connection:
        connection.execute("CREATE TRIGGER fail_node BEFORE INSERT ON agent_dag_nodes "
                           "BEGIN SELECT RAISE(ABORT, 'fixture rollback'); END")
    definition = graph()
    with pytest.raises(AgentTaskError, match="database operation failed"):
        runtime.batches.control("register", {"definition": definition})
    assert runtime.batches.control("list")["batches"] == []


def test_claim_survives_restart_and_never_becomes_proof_of_non_delivery(runtime):
    value = runtime.batches.control("register", {"definition": graph()})
    started = runtime.batches.control("begin", {"batch_id": value["batch_id"],
                                               "definition": graph(), "max_parallel": 4})
    runtime.batches.control("claim", {"batch_id": value["batch_id"], "attempt": started["attempt"], "node_id": "a"})
    runtime.close()
    restored = AgentRuntime(runtime.store.path, targets={"fixture": object()})
    try:
        current = restored.batches.control("get", {"batch_id": value["batch_id"]})
        assert current["state"] == "waiting_review"
        assert current["nodes"][0]["phase"] == "claimed"
        assert not current["resume_permitted"]
        with pytest.raises(AgentTaskError, match="inactive"):
            restored.batches.control("claim", {"batch_id": value["batch_id"],
                                                "attempt": started["attempt"], "node_id": "b"})
        definition = graph()
        with pytest.raises(AgentTaskError, match="explicit recovery"):
            restored.batches.control("begin", {"batch_id": value["batch_id"], "definition": definition,
                                               "max_parallel": 4})
    finally:
        restored.close()


@pytest.mark.parametrize("fault", ["legacy", "duplicates", "cycle", "tag", "unknown"])
def test_invalid_or_unbound_graphs_are_refused_before_registration(runtime, fault):
    definition = graph()
    if fault == "legacy":
        definition["nodes"][0] = {"id": "a", "actions": []}
    elif fault == "duplicates":
        definition["nodes"][1]["task"]["idempotency_key"] = "a"
    elif fault == "cycle":
        definition["nodes"][0]["depends_on"] = ["b"]
    elif fault == "tag":
        definition["nodes"][0]["task"]["spec"]["options"] = {"dag_batch": {"batch_id": "forged"}}
    else:
        definition["nodes"][0]["url"] = "http://unreviewed"
    with pytest.raises((AgentTaskError, DagDefinitionError)):
        runtime.batches.control("register", {"definition": definition})
    assert runtime.batches.control("list")["batches"] == []


def test_graph_tampering_and_closed_runtime_fail_closed(runtime):
    value = runtime.batches.control("register", {"definition": graph()})
    changed = deepcopy(value["definition"])
    changed["nodes"][0]["task"]["spec"]["goal"] = "different"
    with runtime.store.connection(write=True) as connection:
        connection.execute("UPDATE agent_dag_batches SET definition=? WHERE id=?",
                           (json.dumps(changed), value["batch_id"]))
    with pytest.raises(AgentTaskError, match="digest mismatch"):
        runtime.batches.control("get", {"batch_id": value["batch_id"]})
    runtime.close()
    definition = graph()
    with pytest.raises(AgentTaskError, match="closed"):
        runtime.batches.control("register", {"definition": definition})


def test_changed_registered_host_is_refused_without_revealing_credentials(runtime, monkeypatch):
    identity = ["http://127.0.0.1:9", "fixture-initial-credential"]
    monkeypatch.setattr(managed_tasks, "_host_identity", lambda _host: tuple(identity))
    definition = graph()
    definition["nodes"][0]["host"] = "remote"
    with authorization_scope(AuthorizationContext("admin", "admin")):
        value = runtime.batches.control("register", {"definition": definition})
        assert identity[1] not in str(value)
        identity[1] = "fixture-replaced-credential"
        with pytest.raises(AgentTaskError, match="host configuration"):
            runtime.batches.control("begin", {"batch_id": value["batch_id"],
                                               "definition": definition, "max_parallel": 4})
        assert runtime.batches.control("get", {"batch_id": value["batch_id"]})["state"] == "registered"


def test_original_owner_revocation_blocks_admin_delivery_of_registered_work(runtime, tmp_path):
    from je_auto_control.utils.rbac.users import UserStore
    users = UserStore(tmp_path / "users.json")
    users.add_user(user_id="owner", display_name="Owner", role="operator")
    with authorization_scope(AuthorizationContext("owner", "operator", store_path=str(users.path))):
        value = runtime.batches.control("register", {"definition": graph()})
    users.set_role("owner", "viewer")
    definition = graph()
    with authorization_scope(AuthorizationContext("admin", "admin")):
        with pytest.raises(AuthorizationError):
            runtime.batches.control("begin", {"batch_id": value["batch_id"], "definition": definition,
                                               "max_parallel": 4})


def test_nested_managed_operation_is_refused_before_batch_client_contact(monkeypatch):
    from je_auto_control.utils.dag import batch_execution, run_dag
    client = Mock(side_effect=AssertionError("nested batch contacted the coordinator"))
    monkeypatch.setattr(batch_execution, "current_operation", lambda: object())
    monkeypatch.setattr(batch_execution, "AgentRuntimeClient", client)
    definition = graph()
    with pytest.raises(AgentTaskError, match="cannot coordinate"):
        run_dag(definition, batch_id="registered-batch")
    client.assert_not_called()


def test_an_unreadable_batch_cannot_keep_emergency_stop_from_cancelling_tasks(runtime):
    value = runtime.batches.control("register", {"definition": graph()})
    runtime.batches.control("begin", {"batch_id": value["batch_id"], "definition": graph(), "max_parallel": 4})
    with runtime.store.connection(write=True) as connection:
        connection.execute("UPDATE agent_dag_batches SET graph_hash='changed' WHERE id=?", (value["batch_id"],))
    queued = runtime.submit(task()["spec"]).task_id
    result = runtime.stop_all()
    assert runtime.get(queued).state == "cancelled"
    assert result["requested"] == 1
    assert result["cleanup_errors"] == [{"batch_id": value["batch_id"], "error": "AgentTaskError"}]


def until(condition, attempts=500):
    for _attempt in range(attempts):
        if condition():
            return
        threading.Event().wait(0.01)
    raise AssertionError("condition was not reached")


def begun(runtime):
    value = runtime.batches.control("register", {"definition": graph()})
    started = runtime.batches.control("begin", {"batch_id": value["batch_id"], "definition": graph(),
                                               "max_parallel": 4})
    return value["batch_id"], started["attempt"]


def test_emergency_stop_returns_without_waiting_for_a_batch_operation(runtime):
    # It used to wait here for the batch lock, although input had already stopped.
    batch, attempt = begun(runtime)
    running = runtime.submit(task()["spec"]).task_id
    owned, release, admitted = threading.Event(), threading.Event(), []

    def slow_operation():
        with runtime._lock("dag:" + batch):
            owned.set()
            assert release.wait(10)
            admitted.append(runtime.submit(task()["spec"]).task_id)  # a task the operation admits as it ends

    with ThreadPoolExecutor(max_workers=3) as workers:
        operation = workers.submit(slow_operation)
        try:
            assert owned.wait(5)
            result = workers.submit(runtime.stop_all).result(timeout=5)  # while the operation still runs
            assert runtime._token(running).is_cancelled and runtime.get(running).state == "cancelled"
            assert result["requested"] == 1 and result["batch_fence_pending"] == [batch]
            claim = workers.submit(runtime.batches.control, "claim",
                                   {"batch_id": batch, "attempt": attempt, "node_id": "a"})
        finally:
            release.set()
        operation.result(timeout=5)
        with pytest.raises(AgentTaskError):
            claim.result(timeout=5)  # refused by the pending fence or by the pause that followed it
    until(lambda: admitted and runtime.get(admitted[0]).state == "cancelled")
    described = runtime.batches.control("get", {"batch_id": batch})
    assert described["state"] == "waiting_review"
    assert all(node["phase"] == "pending" for node in described["nodes"])


def test_a_batch_whose_stop_is_pending_refuses_progress_but_not_reads(runtime):
    from je_auto_control.utils.agent_runtime.runtime_stop import mark_fencing, unmark_fencing
    batch, attempt = begun(runtime)
    claim = {"batch_id": batch, "attempt": attempt, "node_id": "a"}
    mark_fencing(runtime, batch)
    with pytest.raises(AgentTaskError, match="being stopped"):
        runtime.batches.control("claim", claim)
    assert runtime.batches.control("get", {"batch_id": batch})["state"] == "running"
    unmark_fencing(runtime, batch)
    runtime.batches.control("claim", claim)


def test_a_background_fence_failure_is_reported_by_the_next_stop(runtime):
    from je_auto_control.utils.agent_runtime import runtime_stop
    batch, _attempt = begun(runtime)
    owned, release = threading.Event(), threading.Event()

    def slow_operation():
        with runtime._lock("dag:" + batch):
            owned.set()
            assert release.wait(10)
            with runtime.store.connection(write=True) as connection:  # the batch turns unreadable meanwhile
                connection.execute("UPDATE agent_dag_batches SET graph_hash='changed' WHERE id=?", (batch,))

    with ThreadPoolExecutor(max_workers=2) as workers:
        operation = workers.submit(slow_operation)
        try:
            assert owned.wait(5)
            assert workers.submit(runtime.stop_all).result(timeout=5)["cleanup_errors"] == []
        finally:
            release.set()
        operation.result(timeout=5)
    until(lambda: runtime_stop._fences(runtime).errors)  # the background pause has failed
    failure = {"batch_id": batch, "error": "AgentTaskError"}
    # This stop's own attempt on the still-running batch fails too, then the earlier failure is reported.
    assert runtime.stop_all()["cleanup_errors"] == [failure, failure]
    assert runtime.stop_all()["cleanup_errors"] == [failure]  # reported once
