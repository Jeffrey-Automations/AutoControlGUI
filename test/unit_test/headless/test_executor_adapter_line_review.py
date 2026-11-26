"""Bugs a line-by-line read of the ``action_executor`` adapters turned up.

Each case drives one adapter headlessly, with the device- or screen-touching
call it delegates to replaced, and pins the argument it now reads correctly:
a flag spelled ``"false"``, a JSON string that decodes to a string, a ``NaN``
threshold, an unknown operator, or a result that reported a setting it did
not apply. No ``PySide6``, no real mouse, keyboard, screen or USB device.
"""
from types import SimpleNamespace

import pytest

from je_auto_control.utils.executor import action_executor as ae


# --- flags spelled "false" ---------------------------------------------------

@pytest.fixture()
def usb_commands(monkeypatch):
    """Record what the USB adapters hand the shared command module."""
    from je_auto_control.utils.usb.passthrough import commands
    calls = {}

    def recorder(name):
        def record(*args, **kwargs):
            calls[name] = (args, kwargs)
            return {}
        return record

    for name in ("passthrough_enable", "acl_add", "acl_import"):
        monkeypatch.setattr(commands, name, recorder(name))
    return calls


def test_usb_passthrough_enable_false_string_disables(usb_commands):
    ae._usb_passthrough_enable("false")
    assert usb_commands["passthrough_enable"][0] == (False,)


def test_usb_acl_add_false_string_writes_a_deny_rule(usb_commands):
    ae._usb_acl_add("1234", "abcd", allow="false", prompt_on_open="false")
    kwargs = usb_commands["acl_add"][1]
    assert kwargs["allow"] is False
    assert kwargs["prompt_on_open"] is False


def test_usb_acl_import_false_string_merges(usb_commands):
    ae._usb_acl_import("acl.json", replace="false")
    assert usb_commands["acl_import"][1]["replace"] is False


def _fake_golden_comparison(monkeypatch):
    from je_auto_control.utils import visual_regression
    taken = []
    monkeypatch.setattr(visual_regression, "take_golden",
                        lambda path, region=None: taken.append(path))
    result = SimpleNamespace(matched=False, diff_pct=50.0, differing_pixels=5,
                             total_pixels=10, tolerance_pct=0.0, diff_image=None,
                             summary="differs")
    monkeypatch.setattr(visual_regression, "compare_to_golden",
                        lambda *args, **kwargs: result)
    return taken


def test_assert_visual_create_if_missing_false_string_does_not_create(monkeypatch, tmp_path):
    taken = _fake_golden_comparison(monkeypatch)
    outcome = ae._assert_visual(str(tmp_path / "missing.png"),
                                create_if_missing="false", raise_on_fail="false")
    assert taken == []
    assert outcome["matched"] is False


def test_assert_visual_raise_on_fail_false_string_returns(monkeypatch, tmp_path):
    golden = tmp_path / "golden.png"
    golden.write_bytes(b"x")
    _fake_golden_comparison(monkeypatch)
    assert ae._assert_visual(str(golden), raise_on_fail="false")["matched"] is False


def test_soft_assert_raise_on_fail_false_string_returns():
    outcome = ae._soft_assert([{"value": 1, "op": "eq", "expected": 2}], raise_on_fail="false")
    assert outcome["ok"] is False


def test_fuzzy_ignore_case_false_string_keeps_case():
    assert ae._fuzzy_ratio("ABC", "abc", ignore_case="false")["score"] < 1.0
    assert ae._fuzzy_best_match("ABC", ["abc"], score_cutoff=0.99,
                                ignore_case="false")["match"] is None
    assert ae._fuzzy_dedupe(["ABC", "abc"], threshold=0.99,
                            ignore_case="false")["unique"] == ["ABC", "abc"]


def test_execute_action_dry_run_false_string_executes():
    ran = []
    runner = ae.Executor()
    runner.event_dict["probe_ran"] = lambda: ran.append(True) or "ran"
    runner.execute_action([["probe_ran"]], dry_run="false")
    assert ran == [True]
