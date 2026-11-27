"""The LSP diagnoses action files only, not every JSON document it is sent.

Every local JSON / JSONC file used to be diagnosed as an action list, so an
ordinary ``package.json`` got "action file must be a JSON list" and a JSONC
settings file with comments got "invalid JSON". The server now checks the
document URI against the action-file globs (the client's ``actionFiles``
initialization option, or the defaults the extension ships).
"""
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_LSP_DIR = _REPO / "autocontrol-lsp"
if str(_LSP_DIR) not in sys.path:
    sys.path.insert(0, str(_LSP_DIR))

_PACKAGE_JSON = '{"name": "demo", "version": "1.0.0"}'
_COMMENTED_SETTINGS = '{\n  // editor settings\n  "editor.tabSize": 4,\n}\n'
_BAD_ACTIONS = '[["AC_no_such_command"]]'


def _open(server, uri: str, text: str) -> list:
    server.handle_notification("textDocument/didOpen", {
        "textDocument": {"uri": uri, "languageId": "json", "version": 1, "text": text},
    })
    (payload,) = server.drain_diagnostics()
    assert payload["uri"] == uri
    return payload["diagnostics"]


@pytest.fixture
def server():
    from autocontrol_lsp.server.server import LspServer
    return LspServer()


def test_default_globs_diagnose_an_action_file(server):
    server.dispatch("initialize", {})
    diags = _open(server, "file:///c%3A/work/login.ac.json", _BAD_ACTIONS)
    assert any("unknown AC_ command" in d["message"] for d in diags)


@pytest.mark.parametrize("uri, text", [
    ("file:///c%3A/work/package.json", _PACKAGE_JSON),
    ("file:///c%3A/work/.vscode/settings.json", _COMMENTED_SETTINGS),
    ("untitled:Untitled-1", _BAD_ACTIONS),
])
def test_other_json_is_not_diagnosed(server, uri, text):
    server.dispatch("initialize", {})
    assert _open(server, uri, text) == []


def test_did_change_on_other_json_stays_quiet(server):
    uri = "file:///home/me/proj/tsconfig.json"
    _open(server, uri, "{}")
    server.handle_notification("textDocument/didChange", {
        "textDocument": {"uri": uri, "version": 2},
        "contentChanges": [{"text": "{ // still JSONC\n}"}],
    })
    (payload,) = server.drain_diagnostics()
    assert payload["diagnostics"] == []


def test_client_globs_replace_the_defaults(server):
    server.dispatch("initialize", {
        "initializationOptions": {"actionFiles": ["**/keyword/*.json"]},
    })
    keyword = "file:///c%3A/repo/AutoControl/keyword/broken.json"
    assert _open(server, keyword, _BAD_ACTIONS)
    assert _open(server, "file:///c%3A/repo/x.ac.json", _BAD_ACTIONS) == []
    assert _open(server, "file:///c%3A/repo/package.json", _PACKAGE_JSON) == []


def test_malformed_initialization_option_falls_back_to_defaults():
    from autocontrol_lsp.server.action_files import (
        DEFAULT_ACTION_FILE_GLOBS, ActionFileFilter,
    )
    for options in ({"actionFiles": "**/*.json"}, {"actionFiles": [1]}, "x"):
        selected = ActionFileFilter.from_initialize_params(
            {"initializationOptions": options})
        assert selected.globs == DEFAULT_ACTION_FILE_GLOBS


@pytest.mark.parametrize("glob, path, expected", [
    ("**/*.ac.json", "/a/b/c/x.ac.json", True),
    ("**/*.ac.json", "/a/x.json", False),
    ("**/actions/**/*.json", "/repo/actions/x.json", True),
    ("**/actions/**/*.json", "/repo/actions/sub/x.json", True),
    ("**/actions/*.json", "/repo/actions/sub/x.json", False),
    ("**/*.{ac,flow}.json", "/r/y.flow.json", True),
    ("**/step?.json", "/r/step1.json", True),
    ("**/step?.json", "/r/step12.json", False),
])
def test_glob_semantics(glob, path, expected):
    from autocontrol_lsp.server.action_files import glob_to_regex
    assert bool(glob_to_regex(glob).fullmatch(path)) is expected


def test_windows_uri_matches_an_absolute_glob_without_case():
    from autocontrol_lsp.server.action_files import ActionFileFilter, uri_to_path
    assert uri_to_path("file:///c%3A/Work/a.json") == "c:/Work/a.json"
    selected = ActionFileFilter(["C:/work/**/*.json"])
    assert selected.matches("file:///c%3A/Work/flows/a.json")
    assert not selected.matches("file:///d%3A/Work/flows/a.json")


def test_extension_default_matches_the_server_default():
    """The client selector and the server guard must agree on the default."""
    from autocontrol_lsp.server.action_files import DEFAULT_ACTION_FILE_GLOBS
    manifest = json.loads(
        (_LSP_DIR / "vscode" / "package.json").read_text(encoding="utf-8"))
    setting = manifest["contributes"]["configuration"]["properties"]["autocontrolLsp.actionFiles"]
    assert tuple(setting["default"]) == DEFAULT_ACTION_FILE_GLOBS
    source = (_LSP_DIR / "vscode" / "src" / "extension.ts").read_text(encoding="utf-8")
    literal = json.dumps(list(DEFAULT_ACTION_FILE_GLOBS))
    assert f"const DEFAULT_ACTION_FILES: string[] = {literal};" in source
