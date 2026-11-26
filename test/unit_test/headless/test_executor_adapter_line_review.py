"""Bugs a line-by-line read of the ``action_executor`` adapters turned up.

Each case drives one adapter headlessly, with the device- or screen-touching
call it delegates to replaced, and pins the argument it now reads correctly:
a flag spelled ``"false"``, a JSON string that decodes to a string, a ``NaN``
threshold, an unknown operator, or a result that reported a setting it did
not apply. No ``PySide6``, no real mouse, keyboard, screen or USB device.
"""
import threading
from types import SimpleNamespace

import pytest

from je_auto_control.utils.exception.exceptions import AutoControlActionException
from je_auto_control.utils.executor import action_executor as ae

NAN = float("nan")
#: What a stubbed wait / assertion returns: a pass, so reaching it at all is the bug.
PASSED = SimpleNamespace(to_dict=lambda: {"succeeded": True, "passed": True})


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


# --- JSON strings that decode to something other than a list ----------------

def test_arrange_grid_refuses_a_json_string_that_is_not_a_list(monkeypatch):
    from je_auto_control.utils import window_capture
    moved = []
    monkeypatch.setattr(window_capture, "arrange_grid",
                        lambda titles, **kwargs: moved.append(titles) or 0)
    monkeypatch.setattr(window_capture, "arrange_cascade",
                        lambda titles, **kwargs: moved.append(titles) or 0)
    with pytest.raises(AutoControlActionException):
        ae._arrange_grid('"Notepad"')
    with pytest.raises(AutoControlActionException):
        ae._arrange_cascade('"Notepad"')
    assert moved == []
    assert ae._arrange_grid('["Notepad", "Paint"]') == {"moved": 0, "count": 2}
    assert moved == [["Notepad", "Paint"]]


@pytest.mark.parametrize("call", [
    lambda: ae._collation_sort('"cba"'),
    lambda: ae._format_list('"ab"'),
    lambda: ae._fuzzy_dedupe('"aa"'),
    lambda: ae._fuzzy_best_match("a", '"ab"'),
])
def test_list_arguments_refuse_a_json_string_of_a_string(call):
    with pytest.raises(AutoControlActionException):
        call()


def test_list_arguments_still_take_json_lists():
    assert ae._collation_sort('["b", "a"]')["sorted"] == ["a", "b"]
    assert ae._fuzzy_dedupe('["aa", "aa"]')["unique"] == ["aa"]


# --- NaN thresholds that passed an "absent" check ---------------------------

def test_wait_color_refuses_nan_min_fraction(monkeypatch):
    from je_auto_control.utils import smart_waits
    called = []
    monkeypatch.setattr(smart_waits, "wait_until_color",
                        lambda **kwargs: called.append(kwargs) or PASSED)
    with pytest.raises(AutoControlActionException):
        ae._wait_color([0, 0, 0], min_fraction=NAN, present=False)
    assert called == []


@pytest.mark.parametrize("adapter,function,kwargs", [
    ("_assert_audio", "assert_audio_activity", {"threshold": NAN, "expect_sound": False}),
    ("_assert_video_changes", "assert_video_changes",
     {"video_path": "clip.mp4", "threshold": NAN, "expect_motion": False}),
])
def test_media_assertions_refuse_a_nan_threshold(monkeypatch, adapter, function, kwargs):
    from je_auto_control.utils import media_assert
    called = []
    monkeypatch.setattr(media_assert, function, lambda *a, **k: called.append(k) or PASSED)
    with pytest.raises(AutoControlActionException):
        getattr(ae, adapter)(**kwargs)
    assert called == []


def test_perceptual_diff_refuses_a_nan_max_diff_ratio(monkeypatch):
    from je_auto_control.utils import perceptual_diff
    result = SimpleNamespace(diff_pixels=9, total_pixels=10, diff_ratio=0.9, regions=[])
    monkeypatch.setattr(perceptual_diff, "perceptual_diff", lambda *a, **k: result)
    with pytest.raises(AutoControlActionException):
        ae._perceptual_diff("a.png", "b.png", max_diff_ratio=NAN)


# --- an unknown operator --------------------------------------------------------

def test_expect_poll_refuses_an_unknown_op(monkeypatch):
    monkeypatch.setitem(ae.executor.event_dict, "AC_review_three", lambda: 3)
    with pytest.raises(AutoControlActionException):
        ae._expect_poll(["AC_review_three"], op="eq", expected=5,
                        timeout_s=0.05, interval_s=0.01)


def test_expect_poll_known_and_default_ops_still_work(monkeypatch):
    monkeypatch.setitem(ae.executor.event_dict, "AC_review_three", lambda: 3)
    assert ae._expect_poll(["AC_review_three"], op="equals", expected=3)["ok"] is True
    assert ae._expect_poll(["AC_review_three"])["ok"] is True


# --- a result that reported a setting it did not apply ----------------------

def test_usb_watch_start_reports_the_interval_in_use(monkeypatch):
    from je_auto_control.utils.usb import usb_watcher
    fake = SimpleNamespace(start=lambda: None, is_running=True, poll_interval_s=2.0)
    monkeypatch.setattr(usb_watcher, "default_usb_watcher", lambda: fake)
    assert ae._usb_watch_start(poll_interval_s=0.5)["interval_s"] == 2.0


def test_usb_watcher_exposes_its_poll_interval():
    from je_auto_control.utils.usb.usb_watcher import UsbHotplugWatcher
    assert UsbHotplugWatcher(poll_interval_s=5.0, enumerator=list).poll_interval_s == 5.0


# --- a shared singleton started twice ------------------------------------------

def test_a11y_record_start_from_two_threads_starts_one_recorder(monkeypatch):
    from je_auto_control.utils import accessibility
    both_inside = threading.Barrier(2)
    started = []

    class FakeRecorder:
        def __init__(self, **_kwargs):
            try:
                both_inside.wait(timeout=0.5)  # both callers past the None check
            except threading.BrokenBarrierError:
                pass
            self.is_running = False

        def start(self):
            started.append(self)
            self.is_running = True

        def stop(self):
            self.is_running = False
            return []

    monkeypatch.setattr(accessibility, "AccessibilityRecorder", FakeRecorder)
    monkeypatch.setattr(ae, "_AX_RECORDER_SINGLETON", None)
    threads = [threading.Thread(target=ae._a11y_record_start) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    ae._a11y_record_stop()
    assert len(started) == 1
