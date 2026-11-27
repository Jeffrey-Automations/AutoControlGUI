"""The generated single-file executor honours mandatory signing. No Qt.

``executor_one_file.py`` read its action file with ``read_action_json``, so
``JE_AUTOCONTROL_REQUIRE_SIGNED_ACTIONS`` never looked at it: a tampered or
unsigned file ran. It now reads through the verifying reader, and what runs is
the content that was verified.
"""
import json
import runpy

import pytest

import je_auto_control
from je_auto_control.utils.action_signing import sign_action_file, signer
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.project.template.template_executor import (
    bad_executor_template_1, executor_template_1,
)

REQUIRE_ENV = "JE_AUTOCONTROL_REQUIRE_SIGNED_ACTIONS"
_SIGNING_ENVS = ("JE_AUTOCONTROL_ACTION_SIGNING_PRIVATE_KEY",
                 "JE_AUTOCONTROL_ACTION_SIGNING_PUBLIC_KEY",
                 "JE_AUTOCONTROL_ACCEPT_LEGACY_ACTION_SIGNATURES")
_ACTIONS = [["AC_set_var", {"name": "signed", "value": 1}]]


@pytest.fixture
def dispatched(monkeypatch, tmp_path):
    """Enforce signing with a per-user HMAC key in tmp_path; record what would run."""
    for name in _SIGNING_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(REQUIRE_ENV, "1")
    monkeypatch.setattr(signer, "_default_key_path", lambda: tmp_path / "home" / "key")
    ran: list = []
    monkeypatch.setattr(je_auto_control, "execute_action", ran.append)
    return ran


def _generated(tmp_path, template):
    """Write the action file and the executor exactly as create_template does."""
    actions = tmp_path / "keyword1.json"
    actions.write_text(json.dumps(_ACTIONS), encoding="utf-8")
    script = tmp_path / "executor_one_file.py"
    script.write_text(template.replace("{temp}", repr(str(actions))), encoding="utf-8")
    return actions, script


@pytest.mark.parametrize("template", [executor_template_1, bad_executor_template_1], ids=["one_file", "bad_file"])
def test_a_signed_file_runs_what_was_verified(tmp_path, dispatched, template):
    actions, script = _generated(tmp_path, template)
    sign_action_file(actions)
    runpy.run_path(str(script))
    assert dispatched == [_ACTIONS]


@pytest.mark.parametrize("template", [executor_template_1, bad_executor_template_1], ids=["one_file", "bad_file"])
def test_a_tampered_file_is_refused_and_nothing_runs(tmp_path, dispatched, template):
    actions, script = _generated(tmp_path, template)
    sign_action_file(actions)
    actions.write_text(json.dumps([["AC_shell_command", {"shell_command": "calc"}]]), encoding="utf-8")
    with pytest.raises(AutoControlException, match="failed verification"):
        runpy.run_path(str(script))
    assert dispatched == []


def test_an_unsigned_file_is_refused_and_nothing_runs(tmp_path, dispatched):
    _actions, script = _generated(tmp_path, executor_template_1)
    with pytest.raises(AutoControlException, match="missing signature"):
        runpy.run_path(str(script))
    assert dispatched == []
