"""The executor's named in-memory registries refuse new names past their cap.

``AC_cas_put``, ``AC_dedup_check``, ``AC_idempotency_begin``,
``AC_bulkhead_run``, ``AC_sequence_observe`` and ``AC_outbox_enqueue`` created
one process-wide entry per caller-chosen name with no bound. Now a registry
holds at most ``MAX_REGISTRY_NAMES``; at the cap existing names keep working,
nothing is evicted, and a new name is a framework error naming the registry.
Pure stdlib, no Qt.
"""
import pytest

from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.executor import action_executor as ae
from je_auto_control.utils.executor.action_executor import executor

_SET = [["AC_set_var", {"name": "registry_cap_probe", "value": 1}]]
CASES = [
    ("_VERSIONED_STORES", "versioned store", "AC_cas_put", lambda n: {"name": n, "key": "k", "value": 1}),
    ("_DEDUP_WINDOWS", "dedup window", "AC_dedup_check", lambda n: {"name": n, "message_id": "m"}),
    ("_IDEMPOTENCY_STORES", "idempotency store", "AC_idempotency_begin", lambda n: {"name": n, "key": "k"}),
    ("_BULKHEADS", "bulkhead", "AC_bulkhead_run", lambda n: {"name": n, "max_concurrent": 1, "actions": _SET}),
    ("_SEQUENCE_TRACKERS", "sequence tracker", "AC_sequence_observe",
     lambda n: {"name": n, "stream_id": "s", "seq": 1}),
    ("_OUTBOXES", "outbox", "AC_outbox_enqueue", lambda n: {"name": n, "event": "e"}),
]


def test_the_cap_is_a_documented_constant():
    from je_auto_control.utils.executor.named_registry import MAX_REGISTRY_NAMES
    assert MAX_REGISTRY_NAMES == 1024
    assert all(getattr(ae, attribute).limit == MAX_REGISTRY_NAMES for attribute, *_ in CASES)


@pytest.mark.parametrize(("attribute", "label", "command", "arguments"), CASES,
                         ids=[case[2] for case in CASES])
def test_a_full_registry_refuses_a_new_name_and_keeps_the_old_ones(monkeypatch, attribute, label,
                                                                   command, arguments):
    registry = getattr(ae, attribute)
    held = f"cap-probe-held-{command}"
    executor.execute_one(command, arguments(held))
    monkeypatch.setattr(registry, "limit", len(registry))
    try:
        with pytest.raises(AutoControlException, match=label) as refused:
            executor.execute_one(command, arguments(f"cap-probe-new-{command}"))
        assert "no delete or reset command" in str(refused.value)
        assert f"cap-probe-new-{command}" not in registry
        before = registry.get(held)
        executor.execute_one(command, arguments(held))  # an existing name keeps working
        assert registry.get(held) is before  # and is never evicted or replaced
    finally:
        registry._entries.pop(held, None)  # pylint: disable=protected-access  # reason: test cleanup


def test_the_registry_never_evicts_live_state():
    from je_auto_control.utils.executor.named_registry import NamedRegistry, RegistryFullError
    registry = NamedRegistry("probe", "AC_probe", limit=2)
    first, second = object(), object()
    assert registry.setdefault("a", first) is first
    assert registry.setdefault("b", second) is second
    with pytest.raises(RegistryFullError, match="probe"):
        registry.setdefault("c", object())
    assert registry.setdefault("a", object()) is first
    assert len(registry) == 2 and "c" not in registry
