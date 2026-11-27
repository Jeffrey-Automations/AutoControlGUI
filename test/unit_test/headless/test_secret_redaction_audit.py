"""Secrets stay out of the executor log, its record and the MCP audit file.

Only ``AC_secret_*`` arguments were masked, so the key given to
``AC_sign_action_file`` / ``AC_encrypt_action_file`` (and ``password`` /
``token`` arguments elsewhere) reached the log and every caller of the
result record; the MCP audit log checked top-level names only, missing a
passphrase nested in ``actions`` and any ``key``. All values here are fake.
"""
import json

import pytest

from je_auto_control.utils.executor.action_redaction import describe_action, redact_actions
from je_auto_control.utils.mcp_server.audit import AuditLogger

FAKE = "test-secret-1"


@pytest.mark.parametrize("action", [
    ["AC_sign_action_file", {"path": "a.json", "key": FAKE}],
    ["AC_encrypt_action_file", {"path": "a.json", "output": "b", "key": FAKE}],
    ["AC_jwt_encode", {"claims": {}, "key": FAKE}],
    ["AC_email_trigger_add", {"host": "h", "username": "u", "password": FAKE}],
    ["AC_webhook_add", {"path": "/p", "script_path": "s.json", "token": FAKE}],
    ["AC_loop", {"times": 2, "body": [["AC_sign_action_file", {"path": "a", "key": FAKE}]]}],
])
def test_secret_arguments_never_reach_the_description(action):
    assert FAKE not in describe_action(action)


def test_other_arguments_and_keyboard_keys_stay_readable():
    described = describe_action(["AC_hold_key", {"key": "shift", "duration_s": 1}])
    assert "shift" in described
    assert redact_actions(["AC_sign_action_file", {"path": "a.json", "key": FAKE}])[1]["path"] == "a.json"


@pytest.mark.parametrize("tool, arguments", [
    ("ac_execute_actions", {"actions": [["AC_secret_unlock", {"passphrase": FAKE}]]}),
    ("ac_jwt_encode", {"claims": {}, "key": FAKE}),
    ("ac_something", {"outer": {"inner": {"client_secret": FAKE}}}),
    ("ac_something", {"items": [{"access_token": FAKE}]}),
])
def test_the_mcp_audit_file_holds_no_secret(tmp_path, tool, arguments):
    path = tmp_path / "audit.jsonl"
    AuditLogger(str(path)).record(tool=tool, arguments=arguments, status="ok",
                                  duration_seconds=0.1)
    text = path.read_text(encoding="utf-8")
    assert FAKE not in text
    assert json.loads(text)["tool"] == tool


@pytest.mark.parametrize("action", [
    # The executor accepts a positional argument list as well; its secrets
    # were masked only when named, so these reached the log and record keys.
    ["AC_jwt_encode", [{"sub": "x"}, FAKE]],
    ["AC_jwt_decode", [FAKE, "k"]],
    ["AC_sign_action_file", ["a.json", FAKE]],
    ["AC_sign_action_file", ["a.json", None, "key.pem", FAKE]],
    ["AC_decrypt_action_file", ["a.enc", FAKE]],
    ["AC_notify_webhook", ["https://hooks.example.invalid/" + FAKE, "hi"]],
    ["AC_loop", {"times": 1, "body": [["AC_encrypt_action_file", ["a.json", FAKE]]]}],
])
def test_positional_secret_arguments_never_reach_the_description(action):
    assert FAKE not in describe_action(action)


def test_positional_arguments_that_are_not_secret_stay_readable():
    redacted = redact_actions(["AC_sign_action_file", ["a.json", FAKE]])
    assert redacted == ["AC_sign_action_file", ["a.json", "***"]]
    assert describe_action(["AC_hold_key", ["shift", 1]]) == "['AC_hold_key', ['shift', 1]]"
    assert describe_action(["AC_no_such_command", ["x", FAKE]]).count(FAKE) == 1
