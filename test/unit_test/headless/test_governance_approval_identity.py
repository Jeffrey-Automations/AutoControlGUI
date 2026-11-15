"""Inside an RBAC scope the approval gate's maker and checker are the authenticated user."""
import pytest

from je_auto_control.utils.executor.action_executor import Executor
from je_auto_control.utils.governance.governance import ApprovalGate
from je_auto_control.utils.rbac.authorization import (
    AuthorizationContext, AuthorizationError, authorization_scope,
)

_ALICE = AuthorizationContext(user_id="alice", role="operator")
_BOB = AuthorizationContext(user_id="bob", role="operator")


def test_one_user_cannot_approve_their_own_request_under_another_name():
    gate = ApprovalGate()
    with authorization_scope(_ALICE):
        token = gate.request("deploy", "alice")
        with pytest.raises(AuthorizationError, match="approver 'mallory'"):
            gate.approve(token, "mallory")
        assert gate.approve(token, "") is False  # an empty name is alice: still self-approval
    assert gate.status(token) == "pending"


def test_another_authenticated_user_approves():
    gate = ApprovalGate()
    with authorization_scope(_ALICE):
        token = gate.request("deploy")
    assert gate.get(token)["requester"] == "alice"
    with authorization_scope(_BOB):
        assert gate.approve(token, "Bob") is True  # the same person, as _principal compares
    assert gate.get(token)["approver"] == "bob" and gate.is_approved(token)


def test_a_request_filed_under_another_name_is_refused():
    with authorization_scope(_ALICE), pytest.raises(AuthorizationError, match="requester 'bob'"):
        ApprovalGate().request("deploy", "bob")


def test_outside_rbac_the_supplied_names_are_used_as_before():
    gate = ApprovalGate()
    token = gate.request("deploy", "alice")
    assert gate.approve(token, "alice") is False
    assert gate.approve(token, "bob") is True


def test_the_executor_commands_bind_the_same_way(tmp_path):
    db = str(tmp_path / "approvals.json")
    executor = Executor()
    with authorization_scope(_ALICE):
        token = executor.execute_action(
            [["AC_approval_request", {"action": "deploy", "requester": "alice", "db": db}]])
        token = next(iter(token.values()))["token"]
        refused = executor.execute_action(
            [["AC_approval_approve", {"token": token, "approver": "mallory", "db": db}]],
            raise_on_error=False)
    assert "AuthorizationError" in str(refused)
    with authorization_scope(_BOB):
        executor.execute_action([["AC_approval_approve", {"token": token, "approver": "bob", "db": db}]])
    assert ApprovalGate(db).is_approved(token)
