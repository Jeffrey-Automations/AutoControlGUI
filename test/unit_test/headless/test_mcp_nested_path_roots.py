"""Paths nested in DAG, suite and assertion specs are held to the MCP path roots. No Qt.

``ac_run_dag`` reads every node's ``action_file`` on this machine (a remote
node's actions are loaded here and then sent), ``ac_run_suite`` loads a case's
``data.path`` rows file, and the assertion tools read an image spec's
``template_path`` and a file spec's ``path``. Their objects were declared as a
bare ``{"type": "object"}``, so the configured roots never looked inside.

The real schemas are used; every handler is replaced by a recorder.
"""
import dataclasses
import json

import pytest

from je_auto_control.utils.mcp_server.server import MCPServer
from je_auto_control.utils.mcp_server.tools import build_default_tool_registry
from je_auto_control.utils.path_guard.policy import MCP_CLIENT_ROOTS_ENV, MCP_PATH_ROOTS_ENV

TOOLS = ("ac_run_dag", "ac_run_suite", "ac_assert_all", "ac_assert_any", "ac_assert_eventually")


def _dag(path):
    return {"definition": {"nodes": [{"id": "a", "actions": [["AC_noop"]]},
                                     {"id": "b", "action_file": path, "depends_on": ["a"]}]}}


def _suite(path):
    return {"spec": {"name": "s", "cases": [{"name": "c", "actions": [],
                                            "data": {"kind": "csv", "path": path}}]}}


def _assertions(path):
    return [{"kind": "file", "path": path}, {"kind": "text", "text": "Saved"}]


CASES = {
    "ac_run_dag": _dag,
    "ac_run_suite": _suite,
    "ac_assert_all": lambda path: {"specs": _assertions(path)},
    "ac_assert_any": lambda path: {"specs": [{"kind": "image", "template_path": path}]},
    "ac_assert_eventually": lambda path: {"spec": {"kind": "file", "path": path}},
}


@pytest.fixture(autouse=True)
def _no_ambient_policy(monkeypatch):
    for name in (MCP_PATH_ROOTS_ENV, MCP_CLIENT_ROOTS_ENV, "JE_AUTOCONTROL_MCP_ENV_REF_ALLOW",
                 "JE_AUTOCONTROL_MCP_READONLY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def registry():
    return {tool.name: tool for tool in build_default_tool_registry(read_only=False, aliases=False)}


def _server(registry, calls):
    def recorder(name):
        def handler(**arguments):
            calls.append((name, arguments))
            return {"ran": name}
        return handler
    return MCPServer(tools=[dataclasses.replace(registry[name], handler=recorder(name)) for name in TOOLS])


def _call(server, name, arguments):
    line = server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                          "params": {"name": name, "arguments": arguments}}))
    result = json.loads(line)["result"]
    return result["isError"], "".join(block.get("text", "") for block in result["content"])


@pytest.fixture
def rooted(registry, tmp_path, monkeypatch):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "inside.json").write_text("[]", encoding="utf-8")
    (outside / "secret.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv(MCP_PATH_ROOTS_ENV, str(root))
    calls = []
    return _server(registry, calls), calls, root, outside


@pytest.mark.parametrize("tool", TOOLS)
def test_a_nested_path_outside_the_roots_is_refused_before_the_handler(rooted, tool):
    server, calls, _root, outside = rooted
    is_error, text = _call(server, tool, CASES[tool](str(outside / "secret.json")))
    assert is_error and "outside the allowed" in text
    assert calls == []


@pytest.mark.parametrize("tool", TOOLS)
def test_a_nested_path_inside_the_roots_reaches_the_handler(rooted, tool):
    server, calls, root, _outside = rooted
    is_error, _text = _call(server, tool, CASES[tool](str(root / "inside.json")))
    assert not is_error
    assert [name for name, _ in calls] == [tool]


def test_the_handler_gets_the_canonical_path_that_was_checked(rooted):
    server, calls, root, _outside = rooted
    _call(server, "ac_run_dag", _dag(str(root / "sub" / ".." / "inside.json")))
    node = calls[0][1]["definition"]["nodes"][1]
    assert node["action_file"] == str((root / "inside.json").resolve())
    # Keys outside the declared ones, inline actions included, pass through untouched.
    assert calls[0][1]["definition"]["nodes"][0] == {"id": "a", "actions": [["AC_noop"]]}


def test_non_path_spec_keys_are_left_alone(rooted):
    server, calls, _root, _outside = rooted
    is_error, _ = _call(server, "ac_assert_all", {"specs": [{"kind": "text", "text": "/etc/passwd"}]})
    assert not is_error and calls[0][1]["specs"] == [{"kind": "text", "text": "/etc/passwd"}]


def test_without_roots_nothing_is_checked_or_rewritten(registry, tmp_path):
    calls = []
    server = _server(registry, calls)
    arguments = _dag(str(tmp_path / "anywhere.json"))
    assert not _call(server, "ac_run_dag", arguments)[0]
    assert calls[0][1] == arguments


def test_chatops_context_paths_are_held_to_the_roots(tmp_path):
    from je_auto_control.utils.mcp_server._argument_policy import ArgumentPolicy
    from je_auto_control.utils.mcp_server.tools import build_default_tool_registry
    from je_auto_control.utils.path_guard import PathNotAllowedError
    from je_auto_control.utils.path_guard.policy import PathPolicy
    tool = next(item for item in build_default_tool_registry(read_only=False)
                if item.name == "ac_chatops_dispatch")
    root = tmp_path / "root"
    root.mkdir()
    policy = ArgumentPolicy(PathPolicy(roots=[str(root)]))
    for key in ("script_root", "screenshot_dir"):
        with pytest.raises(PathNotAllowedError):
            policy.apply(tool.name, tool.input_schema, {"message": "/run a.json", "context": {key: str(tmp_path)}})
    policy.apply(tool.name, tool.input_schema, {"message": "hi", "context": {"script_root": str(root), "user": "x"}})
