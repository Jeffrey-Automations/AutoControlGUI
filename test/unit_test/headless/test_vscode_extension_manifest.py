"""Tests for the AutoControl VS Code extension scaffold.

We can't actually run VS Code from CI, but we can:

* lint the manifest (every declared command must appear in the menu /
  activation-events lists too);
* verify the TypeScript entry imports the language-client and
  registers every advertised command + view;
* confirm the bundled REST helpers reference the configurable URL +
  token so a user override actually takes effect.
"""
import json
import re
from pathlib import Path

import pytest


_VSCODE_DIR = Path(__file__).resolve().parents[3] / "autocontrol-lsp" / "vscode"


def _manifest() -> dict:
    return json.loads(
        (_VSCODE_DIR / "package.json").read_text(encoding="utf-8"),
    )


def _extension_source() -> str:
    return (_VSCODE_DIR / "src" / "extension.ts").read_text(encoding="utf-8")


# === Manifest =============================================================

def test_manifest_advertises_run_screenshot_preview_commands():
    pkg = _manifest()
    names = {entry["command"] for entry in pkg["contributes"]["commands"]}
    assert {
        "autocontrol.runScript",
        "autocontrol.takeScreenshot",
        "autocontrol.previewScript",
    } <= names


def test_manifest_activation_events_cover_each_command():
    pkg = _manifest()
    events = set(pkg["activationEvents"])
    names = {entry["command"] for entry in pkg["contributes"]["commands"]}
    for command in names:
        assert f"onCommand:{command}" in events, (
            f"missing activation event for {command}"
        )


def test_manifest_declares_rest_config_properties():
    pkg = _manifest()
    props = pkg["contributes"]["configuration"]["properties"]
    assert "autocontrolLsp.rest.url" in props
    assert "autocontrolLsp.rest.token" in props
    assert props["autocontrolLsp.rest.url"]["default"].startswith("http")


def test_manifest_runs_command_pinned_to_json_files():
    pkg = _manifest()
    for menu_entry in pkg["contributes"]["menus"].get("editor/title", []):
        if menu_entry["command"] == "autocontrol.runScript":
            assert "resourceLangId == json" in menu_entry["when"]
            return
    pytest.fail("autocontrol.runScript not pinned to JSON editor title")


def test_manifest_registers_explorer_view():
    pkg = _manifest()
    explorer_views = pkg["contributes"]["views"]["explorer"]
    assert any(v["id"] == "autocontrolScriptSteps" for v in explorer_views)


def test_manifest_version_bumped_past_scaffold():
    """The scaffold shipped at 0.1.0; completion lifted us past that."""
    pkg = _manifest()
    major, minor, *_ = pkg["version"].split(".")
    assert (int(major), int(minor)) >= (0, 2)


# === Extension source ====================================================

def test_extension_registers_every_declared_command():
    source = _extension_source()
    for command in (
        "autocontrol.runScript",
        "autocontrol.takeScreenshot",
        "autocontrol.previewScript",
    ):
        assert f'registerCommand(\n            "{command}"' in source or \
            f'registerCommand("{command}"' in source, (
                f"extension.ts must register {command}"
            )


def test_extension_starts_language_client_with_python_module():
    source = _extension_source()
    assert "vscode-languageclient/node" in source
    assert "autocontrol_lsp.server" in source
    assert "TransportKind.stdio" in source


def test_extension_reads_rest_url_and_token_from_config():
    source = _extension_source()
    assert "rest.url" in source
    assert "rest.token" in source
    assert "AC_TOKEN" in source


def test_extension_treeview_uses_correct_view_id():
    source = _extension_source()
    assert "autocontrolScriptSteps" in source
    assert "registerTreeDataProvider" in source


def test_extension_only_posts_to_configurable_url():
    """No hardcoded https://example.com / http://localhost links."""
    source = _extension_source()
    hardcoded = re.findall(r'"https?://[^"]+"', source)
    # The only http literal allowed is in the comment / default fallback
    # path; everything else must come from config.
    for literal in hardcoded:
        assert literal in ('"http://127.0.0.1:9939"',), (
            f"unexpected hardcoded URL literal: {literal}"
        )


def test_extension_has_runtime_dependency_on_vscode_languageclient():
    pkg = _manifest()
    deps = {**pkg.get("dependencies", {}),
             **pkg.get("devDependencies", {})}
    assert "vscode-languageclient" in deps


def test_tsconfig_is_strict():
    raw = (_VSCODE_DIR / "tsconfig.json").read_text(encoding="utf-8")
    config = json.loads(raw)
    options = config["compilerOptions"]
    assert options["strict"] is True
    assert options["noImplicitAny"] is True


# === REST calls against the real server ===================================

_REST_CALL = re.compile(r'restRequest\(\s*"(GET|POST)",\s*"([^"]+)"')


def _rest_calls() -> dict:
    """``{path: method}`` for every REST request the extension makes."""
    return {path: method
            for method, path in _REST_CALL.findall(_extension_source())}


def test_extension_rest_calls_use_the_method_each_route_is_registered_for():
    """The screenshot command posted to a GET-only route and got 405."""
    from je_auto_control.utils.rest_api import rest_server
    routes = {"GET": rest_server._GET_ROUTES, "POST": rest_server._POST_ROUTES}
    calls = _rest_calls()
    assert {"/screenshot", "/execute"} <= set(calls)
    for path, method in calls.items():
        assert path in routes[method], f"{method} {path} is not a REST route"
    assert calls["/screenshot"] == "GET"
    assert "postJson(" not in _extension_source()


def test_screenshot_command_round_trip_against_the_rest_server(monkeypatch):
    """The extension's request reaches the handler and gets a PNG it accepts."""
    import base64
    import urllib.request

    from PIL import Image

    from je_auto_control.utils.cv2_utils import screenshot as screenshot_module
    from je_auto_control.utils.rest_api.rest_server import RestApiServer

    monkeypatch.setattr(screenshot_module, "pil_screenshot",
                        lambda *args, **kwargs: Image.new("RGB", (4, 3)))
    server = RestApiServer(host="127.0.0.1", port=0, token="t0k",
                           enable_audit=False)
    server.start()
    try:
        host, port = server.address
        request = urllib.request.Request(
            f"http://{host}:{port}/screenshot",  # NOSONAR loopback test server
            method=_rest_calls()["/screenshot"],
            headers={"Authorization": "Bearer t0k"})
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310  # reason: loopback test server
            status, reply = response.status, json.loads(response.read())
    finally:
        server.stop()
    assert status == 200
    # The fields decodeScreenshot() checks, with the values it requires.
    source = _extension_source()
    assert 'reply.format !== "png"' in source
    assert 'reply.encoding !== "base64"' in source
    assert (reply["format"], reply["encoding"]) == ("png", "base64")
    assert base64.b64decode(reply["data"]).startswith(b"\x89PNG\r\n\x1a\n")


def test_screenshot_command_shows_the_image_and_reports_failures():
    source = _extension_source()
    body = source[source.index("async function takeScreenshot"):]
    body = body[:body.index("\n}\n")]
    assert "decodeScreenshot(reply.body)" in body
    assert "fs.writeFile(file, png)" in body
    assert '"vscode.open"' in body
    assert "reply.body.slice(0, 240)" in body


# === Document selection ==================================================

def _client_options_block() -> str:
    source = _extension_source()
    start = source.index("const clientOptions: LanguageClientOptions = {")
    return source[start:source.index("};", start)]


def test_document_selector_is_the_action_file_globs_not_every_json():
    """Selecting every JSON / JSONC file diagnosed package.json as an action list."""
    block = _client_options_block()
    assert "documentSelector: actionFiles.map(" in block
    assert '({ scheme: "file", pattern })' in block
    assert 'language: "json"' not in block
    assert 'language: "jsonc"' not in block
    assert "initializationOptions: { actionFiles }" in block
    source = _extension_source()
    assert 'config.get<string[]>(\n        "actionFiles", DEFAULT_ACTION_FILES,' in source
    assert "**/*.{json,jsonc}" not in source


def test_action_file_default_selects_neither_package_json_nor_all_json():
    default = _manifest()["contributes"]["configuration"]["properties"][
        "autocontrolLsp.actionFiles"]["default"]
    assert default
    for glob in default:
        assert glob not in ("**/*.json", "**/*.jsonc", "**/*.{json,jsonc}", "**")
        assert "package" not in glob
