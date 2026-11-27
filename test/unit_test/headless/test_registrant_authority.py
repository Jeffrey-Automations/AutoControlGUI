"""Voice commands and macros run where both their registrant and the dispatcher may.

An action list one principal stores (``AC_voice_register``, ``AC_define_macro``)
used to run with the rights of whoever set it off: an operator's list signed an
action file when an administrator dispatched it, and ran unchecked from the GUI
or Python. And one principal could replace another's macro in the shared
registry. Pure stdlib, no Qt, no real input.
"""
import pytest

from je_auto_control.utils.executor.action_executor import executor
from je_auto_control.utils.rbac.authorization import (
    AuthorizationContext, AuthorizationError, authorization_scope,
)
from je_auto_control.utils.rbac.users import Role
from je_auto_control.utils.voice import VoiceRouter

ADMIN = AuthorizationContext("boss", Role.ADMIN)
OPERATOR = AuthorizationContext("owner", Role.OPERATOR)
OTHER = AuthorizationContext("someone-else", Role.OPERATOR)
PRIVILEGED = [["AC_sign_action_file"]]  # needs the admin-only signing capability
_MACRO = "registrant_authority_probe"


@pytest.fixture
def signed(monkeypatch):
    calls = []
    monkeypatch.setitem(executor.event_dict, "AC_sign_action_file", lambda: calls.append("signed"))
    yield calls
    executor.macros.pop(_MACRO, None)


def _register(context, actions=None):
    router = VoiceRouter(threshold=0.6)
    with authorization_scope(context):
        router.register("sign the file", actions or PRIVILEGED)
    return router


def _dispatch(router, context):
    with authorization_scope(context):
        return router.dispatch("sign the file")


@pytest.mark.parametrize("dispatcher", [ADMIN, None], ids=["admin", "trusted-local"])
def test_a_voice_command_does_not_borrow_the_dispatchers_rights(signed, dispatcher):
    outcome = _dispatch(_register(OPERATOR), dispatcher)
    assert outcome["matched"] is True
    assert signed == []
    assert "AuthorizationError" in str(outcome["result"])


def test_a_voice_command_is_still_checked_against_the_dispatcher(signed):
    _dispatch(_register(ADMIN), OPERATOR)
    assert signed == []


@pytest.mark.parametrize("who", [ADMIN, None], ids=["admin", "rbac-off"])
def test_a_voice_command_runs_where_both_may(signed, who):
    _dispatch(_register(who), who)
    assert signed == ["signed"]


def test_a_restricted_registrant_still_runs_what_it_may(signed, monkeypatch):
    ran = []
    monkeypatch.setitem(executor.event_dict, "AC_sign_action_file", lambda: ran.append("drive"))
    from je_auto_control.utils.rbac import policy
    monkeypatch.delitem(policy.COMMAND_CAPABILITIES, "AC_sign_action_file")  # now an ordinary input step
    _dispatch(_register(OPERATOR), None)
    assert ran == ["drive"]


def _define(context, body=None):
    with authorization_scope(context):
        return executor.execute_action(
            [["AC_define_macro", {"name": _MACRO, "body": body or PRIVILEGED}]])


def _call(context):
    with authorization_scope(context):
        return executor.execute_action([["AC_call_macro", {"name": _MACRO}]])


@pytest.mark.parametrize("caller", [ADMIN, None], ids=["admin", "trusted-local"])
def test_a_macro_does_not_borrow_the_callers_rights(signed, caller):
    _define(OPERATOR)
    record = _call(caller)
    assert signed == []
    assert "AuthorizationError" in str(record)


def test_a_macro_runs_where_both_may(signed):
    _define(ADMIN)
    _call(ADMIN)
    _define(None)
    _call(None)
    assert signed == ["signed", "signed"]


def test_a_principal_cannot_replace_another_principals_macro(signed):
    _define(OPERATOR, [["AC_sign_action_file"]])
    record = _define(OTHER, [["AC_sign_action_file"], ["AC_sign_action_file"]])
    assert "AuthorizationError" in str(record)
    assert len(executor.macros[_MACRO]["body"]) == 1
    _define(OPERATOR, [["AC_sign_action_file"], ["AC_sign_action_file"]])  # the owner may
    assert len(executor.macros[_MACRO]["body"]) == 2


def test_a_trusted_local_macro_is_not_replaced_by_a_user(signed):
    _define(None)
    record = _define(OPERATOR, [["AC_sign_action_file"], ["AC_sign_action_file"]])
    assert "AuthorizationError" in str(record)
    assert len(executor.macros[_MACRO]["body"]) == 1


def test_trusted_local_code_may_replace_any_macro(signed):
    _define(OPERATOR)
    _define(None, [["AC_sign_action_file"], ["AC_sign_action_file"]])
    assert len(executor.macros[_MACRO]["body"]) == 2
    _call(None)
    assert signed == ["signed", "signed"]


def test_a_refused_redefinition_is_an_authorization_error(signed):
    from je_auto_control.utils.executor.registrant_authority import define_macro
    macros = {}
    with authorization_scope(OPERATOR):
        define_macro(macros, "m", [], [])
    with authorization_scope(OTHER), pytest.raises(AuthorizationError, match="owner"):
        define_macro(macros, "m", [], [])
