"""Headless tests for the QA suite runner, reports, and quarantine."""
import defusedxml.ElementTree as ET
from pathlib import Path

import pytest

from je_auto_control.utils.quarantine.store import QuarantineStore
from je_auto_control.utils.test_suite import (
    STATUS_PASSED, run_suite, to_junit_xml,
    write_allure_results, write_junit_xml,
)

# Use a filesystem assertion so the pass/fail outcome is deterministic on
# every platform. ``AC_assert_window`` is Windows-only (it raises
# NotImplementedError on macOS / Linux CI, which the suite runner scores as
# *error* rather than pass/fail); ``AC_assert_file`` only touches the
# filesystem and raises ``AutoControlAssertionException`` on mismatch.
_MISSING_FILE = "zzz_no_such_dir_qa/zzz_no_such_file.tmp"
_PASS = ["AC_assert_file", {"path": _MISSING_FILE, "exists": False}]
_FAIL = ["AC_assert_file", {"path": _MISSING_FILE, "exists": True}]


def _spec():
    return {
        "name": "Demo",
        "setup": [["AC_set_var", {"name": "base", "value": 1}]],
        "cases": [
            {"name": "passes", "tags": ["smoke"], "actions": [_PASS]},
            {"name": "fails", "actions": [_FAIL]},
            {"name": "each", "as": "row",
             "data": {"kind": "inline", "rows": [{"u": "a"}, {"u": "b"}]},
             "actions": [["AC_set_var", {"name": "u", "value": "${row.u}"}]]},
        ],
    }


def test_run_suite_scores_cases():
    result = run_suite(_spec(), respect_quarantine=False)
    assert result.total == 4
    assert result.passed == 3
    assert result.failed == 1
    assert result.errored == 0
    assert result.success is False
    names = [c.name for c in result.cases]
    assert names == ["passes", "fails", "each[0]", "each[1]"]


def test_run_suite_tag_filter():
    result = run_suite(_spec(), tags=["smoke"], respect_quarantine=False)
    assert result.total == 1
    assert result.cases[0].name == "passes"
    assert result.cases[0].status == STATUS_PASSED


def test_setup_failure_skips_cases():
    spec = {
        "name": "S", "setup": [_FAIL],
        "cases": [{"name": "c", "actions": [_PASS]}],
    }
    result = run_suite(spec, respect_quarantine=False)
    assert result.setup_error is not None
    assert result.total == 0
    assert result.success is False


def test_quarantine_skips_named_case(monkeypatch):
    import je_auto_control.utils.quarantine as q
    monkeypatch.setattr(q, "quarantined_names", lambda: {"fails"})
    result = run_suite(_spec(), respect_quarantine=True)
    fails = next(c for c in result.cases if c.name == "fails")
    assert fails.status == "skipped"
    assert fails.message == "quarantined"
    # the failing case is now skipped, so the suite has no failures
    assert result.failed == 0


def test_junit_xml_is_wellformed():
    result = run_suite(_spec(), respect_quarantine=False)
    xml = to_junit_xml(result)
    root = ET.fromstring(xml)
    suite = root.find("testsuite")
    assert suite.attrib["tests"] == "4"
    assert suite.attrib["failures"] == "1"
    failures = root.findall(".//failure")
    assert len(failures) == 1


def test_write_junit_and_allure(tmp_path: Path):
    result = run_suite(_spec(), respect_quarantine=False)
    junit = write_junit_xml(result, str(tmp_path / "junit.xml"))
    assert Path(junit).is_file()
    allure = write_allure_results(result, str(tmp_path / "allure"))
    assert len(allure) == 4
    assert all(Path(p).is_file() for p in allure)


# === quarantine store ======================================================

def test_quarantine_store_roundtrip(tmp_path: Path):
    store = QuarantineStore(path=tmp_path / "q.json")
    store.add("flaky.json", reason="manual", flip_rate=0.8)
    assert store.is_quarantined("flaky.json")
    assert "flaky.json" in store.names()
    # persisted across instances
    reloaded = QuarantineStore(path=tmp_path / "q.json")
    assert reloaded.is_quarantined("flaky.json")
    assert reloaded.remove("flaky.json") is True
    assert reloaded.remove("flaky.json") is False


def test_auto_quarantine_from_flakiness(tmp_path: Path):
    from je_auto_control.utils.quarantine.store import (
        auto_quarantine_from_flakiness,
    )
    from je_auto_control.utils.run_history.history_store import HistoryStore
    import je_auto_control.utils.flakiness as flak

    history = HistoryStore()
    for status in ["ok", "error", "ok", "error"]:
        run_id = history.start_run("manual", "j", "flaky.json")
        history.finish_run(run_id, status)

    real_analyze = flak.analyze_flakiness

    def _patched(limit=500, min_runs=2, group_by="script_path"):
        return real_analyze(
            store=history, limit=limit, min_runs=min_runs, group_by=group_by,
        )

    store = QuarantineStore(path=tmp_path / "q.json")
    monkey = pytest.MonkeyPatch()
    monkey.setattr(flak, "analyze_flakiness", _patched)
    try:
        added = auto_quarantine_from_flakiness(
            flip_rate_threshold=0.5, min_runs=2, store=store,
        )
    finally:
        monkey.undo()
    assert any(e.name == "flaky.json" for e in added)
    assert store.is_quarantined("flaky.json")


class _SignalExecutor:
    """Runs a suite's lists; the ``boom`` list raises, every list is recorded."""

    def __init__(self, signal=None):
        self.signal = signal
        self.ran = []

    def execute_action(self, actions, raise_on_error=False):
        assert raise_on_error
        self.ran.append(actions[0][0])
        if actions[0][0] == "boom" and self.signal is not None:
            raise self.signal


def test_a_cancelled_case_ends_the_suite_after_its_teardown():
    """OperationCancelledError is a RuntimeError: it was scored as that case's error and the suite went on."""
    from je_auto_control.utils.exception.control_signals import OperationCancelledError
    runner = _SignalExecutor(OperationCancelledError("request-1"))
    spec = {"cases": [{"name": "a", "actions": [["boom"]]}, {"name": "b", "actions": [["next"]]}],
            "teardown": [["cleanup"]]}
    with pytest.raises(OperationCancelledError):
        run_suite(spec, executor=runner, respect_quarantine=False)
    assert runner.ran == ["boom", "cleanup"]


def test_teardown_runs_to_its_end_when_the_run_is_stopped(tmp_path):
    """Teardown is "always run after", but a stop raised before its first action."""
    from je_auto_control.utils.executor.action_executor import Executor
    from je_auto_control.utils.executor.run_control import ExecutionStopped, StopToken, stoppable_run
    token = StopToken("suite-stop")
    executor = Executor()
    executor.event_dict["AC_probe_stop"] = lambda: token.stop("test")
    cleaned = []
    executor.event_dict["AC_probe_cleanup"] = lambda: cleaned.append(True)
    spec = {"cases": [{"name": "a", "actions": [["AC_probe_stop"], ["AC_probe_stop"]]}],
            "teardown": [["AC_probe_cleanup"]]}
    with stoppable_run(token=token):
        with pytest.raises(ExecutionStopped):
            run_suite(spec, executor=executor, respect_quarantine=False)
    assert cleaned == [True]


def test_a_missing_optional_package_scores_one_case_as_an_error():
    """The executor re-raises ImportError with raise_on_error; it ended the suite with no results."""
    runner = _SignalExecutor(ModuleNotFoundError("no module named 'openpyxl'"))
    result = run_suite({"cases": [{"name": "a", "actions": [["boom"]]}, {"name": "b", "actions": [["next"]]}]},
                       executor=runner, respect_quarantine=False)
    assert [case.status for case in result.cases] == ["error", "passed"]


def test_a_missing_data_source_package_scores_one_case_as_an_error(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise ModuleNotFoundError("no module named 'openpyxl'")

    monkeypatch.setattr("je_auto_control.utils.data_source.load_rows", unavailable)
    result = run_suite({"cases": [{"name": "a", "actions": [["next"]], "data": {"kind": "xlsx"}},
                                  {"name": "b", "actions": [["next"]]}]},
                       executor=_SignalExecutor(), respect_quarantine=False)
    assert [case.status for case in result.cases] == ["error", "passed"]
