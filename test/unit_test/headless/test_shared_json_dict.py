"""Stores sharing a JSON file across processes must not overwrite each other.

The approval gate, the asset store and the locator-repair store each loaded
their file once and wrote back their own copy on every change: two checkers
deciding one request were both told they had succeeded, and an asset or a
suggestion added by another process vanished on the next write. Separate
instances stand in for separate processes here -- each used to hold its own
copy exactly as a process does.
"""
import os
import threading
import time
from pathlib import Path

import pytest

from je_auto_control.utils.assets.assets import AssetStore
from je_auto_control.utils.governance.governance import ApprovalGate
from je_auto_control.utils.json_store import json_store
from je_auto_control.utils.locator_repair.locator_repair import RepairStore


def test_a_request_is_decided_only_once(tmp_path):
    path = str(tmp_path / "gate.json")
    token = ApprovalGate(path).request("deploy", requester="maker")
    first, second = ApprovalGate(path), ApprovalGate(path)   # both loaded while pending
    assert first.approve(token, "checker-a") is True
    assert second.reject(token, "checker-b") is False
    assert ApprovalGate(path).status(token) == "approved"


def test_a_checker_sees_a_decision_made_elsewhere(tmp_path):
    path = str(tmp_path / "gate.json")
    maker = ApprovalGate(path)
    token = maker.request("deploy", requester="maker")
    ApprovalGate(path).approve(token, "checker")
    assert maker.is_approved(token)


def test_assets_added_by_two_stores_both_survive(tmp_path):
    path = str(tmp_path / "assets.json")
    first, second = AssetStore(path), AssetStore(path)
    first.set("a", 1)
    second.set("b", 2)
    names = {asset.name for asset in AssetStore(path).list()}
    assert names == {"a", "b"}


def test_suggestions_recorded_by_two_stores_both_survive(tmp_path):
    path = str(tmp_path / "repair.json")
    first, second = RepairStore(path), RepairStore(path)
    first.record("k1", method="image", confidence=0.5)
    second.record("k2", method="image", confidence=0.5)
    assert {item["key"] for item in RepairStore(path).pending()} == {"k1", "k2"}


def test_concurrent_updates_are_all_kept(tmp_path):
    path = str(tmp_path / "assets.json")
    threads = [threading.Thread(target=lambda n=n: AssetStore(path).set(f"n{n}", n))
               for n in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(AssetStore(path).list()) == 20


def test_a_lock_left_by_a_dead_process_is_taken_over(tmp_path, monkeypatch):
    target = tmp_path / "gate.json"
    lock = tmp_path / "gate.json.lock"
    lock.write_text("", encoding="utf-8")
    old = time.time() - 3600
    os.utime(lock, (old, old))
    ApprovalGate(str(target)).request("deploy")
    assert not lock.exists()


def test_a_held_lock_times_out(tmp_path, monkeypatch):
    monkeypatch.setattr(json_store, "_LOCK_WAIT_S", 0.05)
    (tmp_path / "gate.json.lock").write_text("", encoding="utf-8")
    gate = ApprovalGate(str(tmp_path / "gate.json"))
    with pytest.raises(TimeoutError):
        gate.request("deploy")


def test_a_waiter_that_judged_a_lock_stale_leaves_the_lock_another_waiter_just_took(tmp_path, monkeypatch):
    """Two waiters see one stale lock; the first takes it over, the second must not delete that."""
    monkeypatch.setattr(json_store, "_LOCK_WAIT_S", 0.2)
    target = tmp_path / "gate.json"
    lock = tmp_path / "gate.json.lock"
    lock.write_text("dead-owner", encoding="utf-8")
    old = time.time() - 3600
    os.utime(lock, (old, old))
    real_is_stale = json_store._lock_is_stale
    raced = []

    def stale_then_taken_over(path):
        verdict = real_is_stale(path)
        if verdict and not raced:
            # Between this waiter's verdict and its takeover, the other waiter
            # removed the dead lock and created its own, fresh one.
            path.unlink()
            path.write_text("other-waiter", encoding="utf-8")
            raced.append(True)
        return verdict
    monkeypatch.setattr(json_store, "_lock_is_stale", stale_then_taken_over)
    with pytest.raises(TimeoutError):
        with json_store._file_lock(target):
            pass
    assert lock.read_text(encoding="utf-8") == "other-waiter"


def test_a_holder_whose_lock_was_taken_over_does_not_release_the_new_owner(tmp_path):
    target = tmp_path / "gate.json"
    lock = tmp_path / "gate.json.lock"
    with json_store._file_lock(target):
        # It held on past the stale limit; another process took the lock over.
        lock.unlink()
        lock.write_text("new-owner", encoding="utf-8")
    assert lock.read_text(encoding="utf-8") == "new-owner"


def test_the_lock_file_names_its_owner(tmp_path):
    target = tmp_path / "gate.json"
    with json_store._file_lock(target):
        first = (tmp_path / "gate.json.lock").read_text(encoding="utf-8")
    with json_store._file_lock(target):
        second = (tmp_path / "gate.json.lock").read_text(encoding="utf-8")
    assert first and second and first != second
    assert not (tmp_path / "gate.json.lock").exists()


def test_without_a_path_the_state_stays_in_memory():
    gate = ApprovalGate()
    token = gate.request("deploy", requester="maker")
    assert gate.approve(token, "checker")
    assert gate.is_approved(token)


# --- a damaged file is kept, not erased (quarantine_label) -----------------

def test_a_quarantining_store_moves_a_damaged_file_aside_and_raises(tmp_path):
    path = tmp_path / "store.json"
    path.write_text("{oops", encoding="utf-8")
    state = json_store.SharedJsonDict(path, quarantine_label="test store")
    with pytest.raises(json_store.JsonStoreDamagedError, match="moved to"):
        state.update(lambda data: data.__setitem__("k", 1))
    [kept] = tmp_path.glob("store.json.corrupt-*")
    assert kept.read_text(encoding="utf-8") == "{oops"
    assert not path.exists()


def test_a_quarantining_store_leaves_a_file_it_cannot_read_in_place(tmp_path, monkeypatch):
    # An OSError says nothing about the content: the file is not moved.
    path = tmp_path / "store.json"
    path.write_text('{"k": 1}', encoding="utf-8")

    def locked(self, *args, **kwargs):
        raise PermissionError("locked by antivirus")

    state = json_store.SharedJsonDict(path, quarantine_label="test store")
    monkeypatch.setattr(Path, "read_text", locked)
    with pytest.raises(PermissionError):
        state.read()
    monkeypatch.undo()
    assert state.read() == {"k": 1}
    assert not list(tmp_path.glob("store.json.corrupt-*"))
