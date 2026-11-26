"""Generated documents keep secret references; resolved env:// values stay out of the log.

``AC_generate_sop`` and ``AC_generate_code`` were expanded like any command, so
``${secrets.NAME}`` was written in plaintext into the generated file and the
result, and a loop variable the documented steps bind themselves raised
"Unknown variable". ``AC_resolve_ref`` put an ``env://`` value -- often a
credential -- into the result log. Pure stdlib, no Qt; the vault is faked.
"""
import json
import logging

import pytest

from je_auto_control.utils.executor.action_executor import executor
from je_auto_control.utils.executor.action_redaction import masked_fields, redact_result
from je_auto_control.utils.logging.logging_instance import autocontrol_logger

PLAINTEXT = "plaintext-vault-value-9f3"
ENV_VALUE = "env-credential-value-4c1"
STEPS = [["AC_write", {"write_string": "${secrets.PW}"}],
         ["AC_write", {"write_string": "${doc_user}"}],
         ["AC_write", {"write_string": "${row}"}]]


@pytest.fixture
def fake_vault(monkeypatch):
    from je_auto_control.utils.script_vars import interpolate
    monkeypatch.setattr(interpolate, "_lookup_secret", lambda name: PLAINTEXT)


def _run(*actions):
    record = executor.execute_action([["AC_set_var", {"name": "doc_user", "value": "alice"}], *actions],
                                     raise_on_error=True)
    return list(record.values())[-1]


def test_a_generated_sop_keeps_secret_references_and_unbound_names(fake_vault, tmp_path):
    sop = _run(["AC_generate_sop", {"actions": STEPS, "title": "Log in ${doc_user} ${secrets.PW}"}])
    text = json.dumps(sop)
    assert PLAINTEXT not in text
    assert "${secrets.PW}" in text and "${row}" in text
    assert "alice" in text and "Log in alice" in sop["title"]
    target = tmp_path / "sop.html"
    _run(["AC_generate_sop", {"actions": STEPS, "path": str(target)}])
    written = target.read_text(encoding="utf-8")
    assert PLAINTEXT not in written and "${secrets.PW}" in written and "alice" in written


def test_generated_code_keeps_secret_references_and_unbound_names(fake_vault, tmp_path):
    output = tmp_path / "test_flow.py"
    code = _run(["AC_generate_code", {"source": STEPS, "output": str(output)}])
    for text in (code, output.read_text(encoding="utf-8")):
        assert PLAINTEXT not in text
        assert "${secrets.PW}" in text and "${row}" in text and "alice" in text


def test_a_code_source_path_still_expands_its_variables(fake_vault, tmp_path):
    (tmp_path / "flow.json").write_text(json.dumps(STEPS), encoding="utf-8")
    code = _run(["AC_set_var", {"name": "flow_dir", "value": str(tmp_path)}],
                ["AC_generate_code", {"source": "${flow_dir}/flow.json"}])
    assert PLAINTEXT not in code and "${secrets.PW}" in code


def test_ordinary_commands_still_expand_secrets(fake_vault):
    assert _run(["AC_set_var", {"name": "probe", "value": "${secrets.PW}"}]) == PLAINTEXT


@pytest.fixture
def log_text(monkeypatch):
    monkeypatch.setenv("AC_TEST_REF_CREDENTIAL", ENV_VALUE)
    lines = []
    handler = logging.Handler(logging.DEBUG)
    handler.emit = lambda record: lines.append(record.getMessage())
    autocontrol_logger.addHandler(handler)
    try:
        yield lines
    finally:
        autocontrol_logger.removeHandler(handler)


def test_a_resolved_env_value_is_returned_but_never_logged(log_text):
    record = executor.execute_action([["AC_resolve_ref", {"ref": "env://AC_TEST_REF_CREDENTIAL"}],
                                      ["AC_resolve_refs", {"obj": {"k": ["env://AC_TEST_REF_CREDENTIAL"]}}]])
    values = list(record.values())
    assert values[0] == {"value": ENV_VALUE}  # still returned to the caller
    assert values[1] == {"resolved": {"k": [ENV_VALUE]}}
    assert log_text and not any(ENV_VALUE in line for line in log_text)


def test_a_resolved_value_is_masked_in_the_displayed_result():
    assert redact_result("AC_resolve_ref", {"value": ENV_VALUE}) == {"value": "***"}
    assert [field.path for field in masked_fields("AC_resolve_ref", {"value": ENV_VALUE})] == [("value",)]
    nested = {"execute: ['AC_resolve_ref', {'ref': 'env://X'}]": {"value": ENV_VALUE}}
    assert ENV_VALUE not in str(redact_result("AC_execute_action", nested))
    assert redact_result("AC_resolve_refs", {"resolved": {"k": [ENV_VALUE]}}) == {"resolved": "***"}
    assert redact_result("AC_get_var", {"value": "plain"}) == {"value": "plain"}
