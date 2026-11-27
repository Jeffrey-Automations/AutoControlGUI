"""Headless tests for the transactional outbox. No Qt."""
import json
from pathlib import Path

import pytest

import je_auto_control as ac
from je_auto_control.utils.outbox import Outbox


def test_enqueue_marks_pending():
    box = Outbox()
    first = box.enqueue({"type": "a"})
    box.enqueue({"type": "b"})
    assert first == "1"
    assert [e["event"]["type"] for e in box.pending()] == ["a", "b"]


def test_drain_delivers_all():
    box = Outbox()
    box.enqueue({"n": 1})
    box.enqueue({"n": 2})
    seen = []
    result = box.drain(seen.append)
    assert result == {"sent": 2, "failed": 0, "remaining": 0}
    assert [e["n"] for e in seen] == [1, 2]
    assert box.pending() == []


def test_drain_retries_then_dead_letters():
    box = Outbox()
    box.enqueue({"n": 1})

    def always_fail(_event):
        raise RuntimeError("sink down")

    # Below max_attempts: stays pending for retry.
    for _ in range(4):
        box.drain(always_fail, max_attempts=5)
    assert len(box.pending()) == 1
    assert box.dead_letters() == []
    # Fifth attempt exhausts and dead-letters.
    box.drain(always_fail, max_attempts=5)
    assert box.pending() == []
    dead = box.dead_letters()
    assert len(dead) == 1
    assert dead[0]["error"] == "sink down"


def test_drain_resumes_after_transient_failure():
    box = Outbox()
    box.enqueue({"n": 1})
    calls = {"count": 0}

    def flaky(_event):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("blip")

    box.drain(flaky)             # fails, stays pending
    result = box.drain(flaky)    # succeeds now
    assert result["sent"] == 1
    assert box.pending() == []


def test_max_batch_limits_delivery():
    box = Outbox()
    for i in range(5):
        box.enqueue({"n": i})
    sent = []
    result = box.drain(sent.append, max_batch=2)
    assert result == {"sent": 2, "failed": 0, "remaining": 3}


def test_save_load_round_trip(tmp_path):
    box = Outbox()
    box.enqueue({"n": 1})
    path = str(tmp_path / "outbox.json")
    box.save(path)
    restored = Outbox.load(path)
    assert len(restored.pending()) == 1
    assert restored.enqueue({"n": 2}) == "2"   # counter preserved


# --- retention: sent entries were kept for ever -----------------------------

class _Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def _send(box, count):
    for index in range(count):
        box.enqueue({"n": index})
    box.drain(lambda _event: None, max_batch=count)


def test_sent_entries_are_capped_by_default():
    box = Outbox()
    _send(box, 1005)
    sent = [entry for entry in box.to_dict()["events"] if entry["status"] == "sent"]
    assert len(sent) == 1000
    assert sent[0]["event"] == {"n": 5}, "the oldest sent entries go first"


def test_the_sent_cap_is_configurable_and_keeps_pending_and_failed():
    box = Outbox(max_sent=2)
    box.enqueue({"kind": "dead"})
    box.drain(_always_fail, max_attempts=1)
    _send(box, 4)
    box.enqueue({"kind": "waiting"})
    events = box.to_dict()["events"]
    assert [entry["status"] for entry in events] == ["failed", "sent", "sent", "pending"]
    assert len(box.dead_letters()) == 1
    assert box.pending()[0]["event"] == {"kind": "waiting"}


def _always_fail(_event):
    raise RuntimeError("sink down")


def test_sent_entries_older_than_the_age_bound_are_pruned():
    clock = _Clock()
    box = Outbox(max_sent_age_s=60.0, clock=clock)
    _send(box, 2)
    box.enqueue({"kind": "dead"})
    box.drain(_always_fail, max_attempts=1)
    clock.now += 61.0
    box.enqueue({"kind": "fresh"})
    box.enqueue({"kind": "waiting"})
    box.drain(lambda _event: None, max_batch=1)  # a drain prunes
    events = box.to_dict()["events"]
    assert [entry["status"] for entry in events] == ["failed", "sent", "pending"]
    assert events[1]["event"] == {"kind": "fresh"}
    clock.now += 10 * 86400.0
    box.prune_sent()
    assert [entry["status"] for entry in box.to_dict()["events"]] == ["failed", "pending"]


def test_the_default_age_bound_is_seven_days():
    clock = _Clock()
    box = Outbox(clock=clock)
    _send(box, 1)
    clock.now += 7 * 86400 - 1
    _send(box, 1)
    assert len(box.to_dict()["events"]) == 2
    clock.now += 2
    _send(box, 1)
    assert len(box.to_dict()["events"]) == 2


def test_a_retention_bound_can_be_switched_off():
    box = Outbox(max_sent=None, max_sent_age_s=None)
    _send(box, 1003)
    assert len(box.to_dict()["events"]) == 1003


def test_bad_retention_bounds_are_refused():
    for options in ({"max_sent": -1}, {"max_sent": True}, {"max_sent_age_s": -1.0},
                    {"max_sent_age_s": float("nan")}):
        with pytest.raises(ValueError):
            Outbox(**options)


def test_a_file_without_sent_times_loads_unchanged(tmp_path):
    # Written by the previous code: no "sent_at", no retention fields.
    old = {"counter": 3, "events": [
        {"id": "1", "event": {"n": 1}, "status": "sent", "attempts": 1},
        {"id": "2", "event": {"n": 2}, "status": "failed", "attempts": 5, "error": "x"},
        {"id": "3", "event": {"n": 3}, "status": "pending", "attempts": 0}]}
    path = tmp_path / "outbox.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    assert Outbox.load(str(path)).to_dict() == old


def test_a_file_written_now_loads_in_the_previous_code(tmp_path):
    box = Outbox()
    _send(box, 1)
    box.enqueue({"n": "pending"})
    path = str(tmp_path / "outbox.json")
    box.save(path)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert set(data) == {"counter", "events"}
    for entry in data["events"]:
        # What the previous Outbox read from each entry, with the same types.
        assert {"id", "event", "status", "attempts"} <= set(entry)
        assert isinstance(entry["attempts"], int) and isinstance(entry["id"], str)
        assert set(entry) - {"id", "event", "status", "attempts", "error"} <= {"sent_at"}
    assert int(data["counter"]) == 2
    assert [entry["status"] for entry in data["events"]] == ["sent", "pending"]


def test_loading_applies_the_retention_bounds(tmp_path):
    box = Outbox(max_sent=None)
    _send(box, 5)
    path = str(tmp_path / "outbox.json")
    box.save(path)
    assert len(Outbox.load(path, max_sent=2).to_dict()["events"]) == 2
    assert len(Outbox.from_dict(box.to_dict(), max_sent=3).to_dict()["events"]) == 3


# --- wiring ---------------------------------------------------------------

def test_executor_round_trip():
    name = "outbox-exec-test"
    rec = ac.execute_action([[
        "AC_outbox_enqueue", {"name": name, "event": '{"type": "x"}'}]])
    out = next(v for v in rec.values() if isinstance(v, dict))
    assert out["id"] == "1"
    assert out["pending"] == 1
    rec2 = ac.execute_action([["AC_outbox_pending", {"name": name}]])
    pending = next(v for v in rec2.values() if isinstance(v, dict))["pending"]
    assert pending[0]["event"]["type"] == "x"


def test_wiring():
    known = ac.executor.known_commands()
    assert {"AC_outbox_enqueue", "AC_outbox_pending"} <= set(known)
    from je_auto_control.utils.mcp_server.tools import build_default_tool_registry
    names = {t.name for t in build_default_tool_registry()}
    assert {"ac_outbox_enqueue", "ac_outbox_pending"} <= names
    from je_auto_control.gui.script_builder.command_schema import _build_specs
    specs = {s.command for s in _build_specs()}
    assert {"AC_outbox_enqueue", "AC_outbox_pending"} <= specs


def test_facade_exports():
    assert hasattr(ac, "Outbox")
    assert "Outbox" in ac.__all__


def test_a_stop_or_cancel_ends_the_drain_without_spending_an_attempt():
    """A stop counted as a failed delivery for every entry left in the batch, up to dead-lettering it."""
    from concurrent.futures import CancelledError
    import pytest
    from je_auto_control.utils.exception.control_signals import OperationCancelledError
    from je_auto_control.utils.executor.run_control import ExecutionStopped
    for signal in (ExecutionStopped("run"), OperationCancelledError("request"), CancelledError()):
        box = Outbox()
        box.enqueue({"n": 1})
        box.enqueue({"n": 2})
        seen = []

        def sink(event, raised=signal, calls=seen):
            calls.append(event)
            raise raised

        with pytest.raises(type(signal)):
            box.drain(sink, max_attempts=1)
        assert seen == [{"n": 1}]
        assert [entry["attempts"] for entry in box.pending()] == [0, 0]
        assert box.dead_letters() == []
