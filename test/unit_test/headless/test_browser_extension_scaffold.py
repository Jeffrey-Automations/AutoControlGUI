"""Tests for the AutoControl Web Recorder browser extension.

We can't actually load the extension into a browser from CI, but we
can lint the manifest (MV3 schema, permissions, file references) and
mirror the ``actionFor`` translation logic in Python so the contract
between captured DOM events and AC_web_* JSON stays stable as the
extension evolves.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest


_EXT_DIR = Path(__file__).resolve().parents[3] / "browser-extension"


def _manifest() -> dict:
    return json.loads(
        (_EXT_DIR / "manifest.json").read_text(encoding="utf-8"),
    )


# === Manifest ============================================================

def test_manifest_uses_manifest_v3():
    pkg = _manifest()
    assert pkg["manifest_version"] == 3
    assert pkg["name"] == "AutoControl Web Recorder"


def test_manifest_declares_required_permissions():
    pkg = _manifest()
    required = {"activeTab", "scripting", "storage", "downloads"}
    assert required <= set(pkg["permissions"])


def test_manifest_files_exist():
    pkg = _manifest()
    relative_paths = [
        pkg["background"]["service_worker"],
        pkg["action"]["default_popup"],
    ]
    for content in pkg.get("content_scripts", []):
        relative_paths.extend(content.get("js", []))
    for path in relative_paths:
        assert (_EXT_DIR / path).is_file(), f"missing extension file: {path}"


def _icon_paths(value) -> list:
    """``default_icon`` / ``icons`` may be one path or a ``{size: path}`` map."""
    if isinstance(value, str):
        return [value]
    return list((value or {}).values())


def _manifest_resource_paths(pkg: dict) -> list:
    """Every file path the manifest names, wherever MV3 lets one appear."""
    paths = [pkg.get("background", {}).get("service_worker")]
    action = pkg.get("action", {})
    paths.append(action.get("default_popup"))
    paths.extend(_icon_paths(action.get("default_icon")))
    paths.extend(_icon_paths(pkg.get("icons")))
    paths.extend([pkg.get("options_page"), pkg.get("options_ui", {}).get("page"),
                  pkg.get("devtools_page"), pkg.get("side_panel", {}).get("default_path")])
    for content in pkg.get("content_scripts", []):
        paths.extend(content.get("js", []) + content.get("css", []))
    for entry in pkg.get("web_accessible_resources", []):
        paths.extend(entry.get("resources", []))
    return [path for path in paths if path]


def test_every_manifest_resource_path_exists():
    """A fresh checkout loads unpacked only if every file the manifest names ships with it."""
    pkg = _manifest()
    paths = _manifest_resource_paths(pkg)
    assert "icons/icon16.png" in paths  # the collector sees the icon maps
    missing = [path for path in paths if not (_EXT_DIR / path).is_file()]
    assert not missing, f"manifest names files the extension does not ship: {missing}"


def test_manifest_resources_are_tracked_by_git():
    """Existing on this disk is not enough: a clean checkout has only what git tracks."""
    try:
        listing = subprocess.run(
            ["git", "ls-files", "--", "browser-extension"], cwd=_EXT_DIR.parent,
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        pytest.skip(f"git is not usable here: {error}")
    if listing.returncode != 0:
        pytest.skip("not a git checkout")
    tracked = set(listing.stdout.splitlines())
    untracked = [path for path in _manifest_resource_paths(_manifest())
                 if f"browser-extension/{path}" not in tracked]
    assert not untracked, f"manifest names files git does not track: {untracked}"


_PNG_SIGNATURE =bytes([0x89]) + b"PNG\r\n\x1a\n"


def _png_size(path: Path) -> tuple:
    """(width, height) from a PNG's IHDR chunk; fails on anything that is not a PNG."""
    raw = path.read_bytes()
    assert raw[:8] == _PNG_SIGNATURE, f"{path.name} is not a PNG"
    assert raw[12:16] == b"IHDR", f"{path.name} has no IHDR chunk first"
    return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")


def test_manifest_icons_are_pngs_of_the_declared_size():
    pkg = _manifest()
    declared = dict(pkg["icons"])
    assert declared == pkg["action"]["default_icon"]
    for size, path in declared.items():
        icon = _EXT_DIR / path
        assert icon.is_file(), f"missing icon: {path}"
        assert _png_size(icon) == (int(size), int(size))


def test_manifest_action_popup_is_html():
    pkg = _manifest()
    popup = pkg["action"]["default_popup"]
    assert popup.endswith(".html")


def test_manifest_content_script_targets_all_urls():
    pkg = _manifest()
    matches = pkg["content_scripts"][0]["matches"]
    assert "<all_urls>" in matches


# === actionFor mirror ====================================================
#
# The JS lives in background.js and we don't run a Node interpreter
# from pytest — so this test re-implements the *same* translation
# rules and checks the JS source line-by-line against the contract.


def _background_source() -> str:
    return (_EXT_DIR / "background.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("event_type,wr_command", [
    ("click", "WR_left_click"),
    ("input", "WR_send_keys_to_element"),
    ("submit", "WR_element_submit"),
    ("key", "WR_press_key"),
])
def test_background_maps_event_type_to_wr_command(event_type, wr_command):
    source = _background_source()
    pattern = re.compile(
        rf'case "{event_type}":[^}}]*action: "{wr_command}"',
        re.DOTALL,
    )
    assert pattern.search(source), (
        f"background.js missing {event_type} → {wr_command} mapping"
    )


def test_background_navigate_event_emits_ac_web_open():
    source = _background_source()
    pattern = re.compile(
        r'case "navigate":[^}]*"AC_web_open"',
        re.DOTALL,
    )
    assert pattern.search(source)


def test_background_unknown_event_returns_null():
    source = _background_source()
    assert "default:" in source
    assert "return null;" in source


def test_background_uses_chrome_storage_local():
    source = _background_source()
    assert "chrome.storage.local" in source


def test_background_handles_start_stop_export_commands():
    source = _background_source()
    for command in ("start", "stop", "export", "status", "reset", "event"):
        assert f'case "{command}":' in source, (
            f"background.js missing handler for {command!r}"
        )


def test_background_export_serialises_with_pretty_indent():
    source = _background_source()
    assert "JSON.stringify(state.actions, null, 2)" in source


# === Content script ======================================================

def _content_source() -> str:
    return (_EXT_DIR / "content_script.js").read_text(encoding="utf-8")


def test_content_script_listens_for_click_change_submit():
    source = _content_source()
    for event_name in ("click", "change", "submit"):
        assert f'addEventListener("{event_name}"' in source


def test_content_script_uses_data_testid_for_selectors():
    source = _content_source()
    assert "data-testid" in source
    assert "data-cy" in source  # legacy Cypress projects use data-cy


def test_content_script_prefers_id_over_data_attribute():
    """The selector builder must short-circuit on element.id first."""
    source = _content_source()
    id_match = source.index("element.id")
    test_match = source.index("data-testid")
    assert id_match < test_match


def test_content_script_emits_navigate_event_on_load():
    source = _content_source()
    assert 'type: "navigate"' in source


# === Popup ==============================================================

def test_popup_html_references_popup_js():
    raw = (_EXT_DIR / "popup.html").read_text(encoding="utf-8")
    assert 'src="popup.js"' in raw


def test_popup_buttons_are_wired_up():
    raw = (_EXT_DIR / "popup.js").read_text(encoding="utf-8")
    for button_id in ("start", "stop", "reset", "export"):
        assert f'getElementById("{button_id}")' in raw


def test_popup_export_downloads_with_chrome_downloads_api():
    raw = (_EXT_DIR / "popup.js").read_text(encoding="utf-8")
    assert "chrome.downloads.download" in raw
    assert "autocontrol-recording.json" in raw


# === Docs ================================================================

def test_readme_mentions_load_unpacked_and_export_flow():
    raw = (_EXT_DIR / "README.md").read_text(encoding="utf-8")
    assert "Load unpacked" in raw
    assert "Download JSON" in raw
    assert "AC_web_open" in raw
