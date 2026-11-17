"""Every ``AC_*`` command has an RBAC decision, and an executor command agrees with its MCP twin."""
from je_auto_control.utils.executor.action_executor import Executor
from je_auto_control.utils.mcp_server.tools import build_default_tool_registry
from je_auto_control.utils.rbac.authorization import AuthorizationContext, authorization_scope
from je_auto_control.utils.rbac.command_review import OPERATOR_COMMANDS, OPERATOR_NOTES
from je_auto_control.utils.rbac.policy import COMMAND_CAPABILITIES, capability_for_tool
from je_auto_control.utils.rbac.users import Capability

_ADMIN_ONLY = {Capability.MANAGE_HOSTS, Capability.MANAGE_USERS, Capability.READ_AUDIT,
               Capability.SIGN_ACTIONS}


def _known() -> set:
    # A fresh executor: the shared one also holds what other tests registered.
    return Executor().known_commands()


def _tool_capabilities() -> dict:
    return {tool.name: capability_for_tool(tool.name, bool(tool.annotations.read_only))
            for tool in build_default_tool_registry(read_only=False)}


def test_every_command_has_exactly_one_decision():
    listed, operator, noted = set(COMMAND_CAPABILITIES), set(OPERATOR_COMMANDS), set(OPERATOR_NOTES)
    assert not listed & operator and not listed & noted and not operator & noted
    undecided = sorted(_known() - listed - operator - noted)
    assert not undecided, (
        f"{undecided}: decide each one -- COMMAND_CAPABILITIES in utils/rbac/policy.py when it reaches "
        "admin-only state, otherwise OPERATOR_COMMANDS in utils/rbac/command_review.py")


def test_the_review_names_only_commands_that_exist():
    assert not (set(OPERATOR_COMMANDS) | set(OPERATOR_NOTES)) - _known()
    assert all(reason.strip() for reason in OPERATOR_NOTES.values())


def test_a_listed_command_needs_what_its_mcp_twin_needs():
    tools = _tool_capabilities()
    differ = {name: (needed, tools[f"ac_{name[3:]}"]) for name, needed in COMMAND_CAPABILITIES.items()
              if f"ac_{name[3:]}" in tools and tools[f"ac_{name[3:]}"] != needed}
    assert not differ


def test_no_operator_command_has_an_admin_only_mcp_twin():
    tools = _tool_capabilities()
    raised = {name: tools[f"ac_{name[3:]}"] for name in set(OPERATOR_COMMANDS) | set(OPERATOR_NOTES)
              if tools.get(f"ac_{name[3:]}") in _ADMIN_ONLY}
    assert not raised, f"{raised}: the action-list path would skip what the tool requires"


def test_a_privileged_command_inside_blocks_and_branches_is_still_refused(monkeypatch):
    calls = []
    # Patched where AC_user_list's adapter looks it up at call time, so a parallel branch's
    # fresh executor (stock commands only) reaches the recorder too.
    monkeypatch.setattr("je_auto_control.utils.rbac.admin.list_users",
                        lambda *_a, **_k: calls.append("ran") or [])
    nested = ["AC_user_list"]
    lists = {
        "parallel": [["AC_parallel", {"branches": [[nested]]}]],
        "loop": [["AC_loop", {"times": 1, "body": [nested]}]],
        "try": [["AC_try", {"body": [nested]}]],
        "macro": [["AC_define_macro", {"name": "m", "body": [nested]}], ["AC_call_macro", {"name": "m"}]],
        "run_stoppable": [["AC_run_stoppable", {"body": [nested]}]],
        "execute_action": [["AC_execute_action", {"action_list": [nested]}]],
    }
    operator = AuthorizationContext(user_id="op", role="operator")
    for label, actions in lists.items():
        with authorization_scope(operator):
            Executor().execute_action(actions, raise_on_error=False)
        assert calls == [], label
    with authorization_scope(AuthorizationContext(user_id="root", role="admin")):
        Executor().execute_action(lists["parallel"], raise_on_error=False)
    assert calls == ["ran"], "the recorder is reached when the role allows it"
