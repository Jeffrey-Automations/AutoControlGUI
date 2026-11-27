"""Scope is checked at every step of a capture, the full checkpoint at a bounded rate. No Qt."""
import pytest

from je_auto_control.utils.agent_runtime import capture_checkpoint as module


def test_the_first_call_and_each_elapsed_interval_run_the_full_checkpoint(monkeypatch):
    now, events = [0.0], []
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    check = module.capture_checkpoint(lambda: events.append("scope"), lambda: events.append("full"))
    check()
    now[0] = 0.01
    check()
    now[0] = 0.06
    check()
    assert events == ["scope", "full", "scope", "scope", "full"]


def test_a_failed_full_checkpoint_is_repeated_on_the_next_call(monkeypatch):
    monkeypatch.setattr(module.time, "monotonic", lambda: 5.0)
    calls = []

    def full():
        calls.append(True)
        raise RuntimeError("revoked")
    check = module.capture_checkpoint(lambda: None, full)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            check()
    assert len(calls) == 2


def test_a_scope_failure_is_never_throttled(monkeypatch):
    monkeypatch.setattr(module.time, "monotonic", lambda: 5.0)
    live = [True]

    def validate():
        if not live[0]:
            raise RuntimeError("scope changed")
    check = module.capture_checkpoint(validate, lambda: None)
    check()
    live[0] = False
    with pytest.raises(RuntimeError, match="scope changed"):
        check()
