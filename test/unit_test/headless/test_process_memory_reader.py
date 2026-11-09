"""Reviewed semantic memory observations against an owned synthetic process provider."""
from concurrent.futures import CancelledError
from asyncio import CancelledError as AsyncCancelledError
from dataclasses import replace
import struct
import threading

import pytest

from je_auto_control.utils.exception.control_signals import OperationCancelledError
from je_auto_control.utils.executor.run_control import ExecutionStopped
from je_auto_control.utils.process_memory.models import (
    FailureReason, MemoryObservationError, MemoryRegion, Observation, ObservationFailure,
    ProcessIdentity, ReadPlan, ReviewedProbe,
)
from je_auto_control.utils.process_memory.reader import ProcessMemoryReader


IDENTITY = ProcessIdentity("host-1", "session-1", 42, 900, "fixture-sha256", "1", "x64", 64)
ADDRESS = 4096
SCHEMA = struct.Struct("<I12s")
PAYLOAD = SCHEMA.pack(17, b"ready")


def decode(raw, fields):
    if len(raw) != SCHEMA.size:
        raise ValueError("private decoder detail")
    document_id, state = SCHEMA.unpack(raw)
    state = state.rstrip(b"\0").decode("ascii")
    if state not in {"ready", "busy", "done"}:
        raise ValueError("unrecognized private value")
    values = {"document_id": document_id, "job_status": state}
    return {name: values[name] for name in fields}


def probe(**changes):
    original = ReviewedProbe("fixture-document", "1", IDENTITY.executable, ("1",), ("x64",),
                             ("document_id", "job_status"), 64, 8, 1.0, 32,
                             lambda identity: ReadPlan(ADDRESS, SCHEMA.size), decode)
    return replace(original, **changes)


class Handle:
    def __init__(self):
        self.current_identity = IDENTITY
        self.memory = {ADDRESS + offset: value for offset, value in enumerate(PAYLOAD)}
        self.memory.update({ADDRESS - 8 + i: value for i, value in enumerate((2).to_bytes(8, "little"))})
        self.regions = [MemoryRegion(ADDRESS - 8, 8 + SCHEMA.size, ADDRESS - 8, 4, True, True, False)]
        self.reads = []
        self.closed = 0
        self.fail_close = False
        self.after_read = lambda: None
        self.transform = lambda value: value

    def identity(self):
        return self.current_identity

    def query_region(self, address):
        return next(region for region in self.regions if region.base <= address < region.base + region.size)

    def read(self, address, size):
        self.reads.append((address, size))
        value = bytes(self.memory[i] for i in range(address, address + size))
        self.after_read()
        return self.transform(value)

    def close(self):
        self.closed += 1
        if self.fail_close:
            raise OSError("SECRET close native address 0xfeed")


class Provider:
    def __init__(self, *handles):
        self.handles = list(handles or [Handle()])
        self.opened = []

    def open_readonly(self, identity):
        handle = self.handles[len(self.opened)]
        self.opened.append(identity)
        return handle


def observe(provider, reviewed=None, fields=("document_id", "job_status"), **options):
    return ProcessMemoryReader(provider).observe(IDENTITY, reviewed or probe(), fields,
                                                 target_id="fixture-document-17", **options)


def test_semantic_observation_has_exact_values_and_no_raw_identity_or_memory():
    provider = Provider()
    result = observe(provider)
    assert isinstance(result, Observation)
    assert result.fields == (("document_id", 17), ("job_status", "ready"))
    assert result.source == "process_memory" and result.complete
    assert result.identity_digest == IDENTITY.digest
    assert result.identity_digest != replace(IDENTITY, birth=901).digest
    assert result.consistency == "best_effort"
    assert result.bytes_read == SCHEMA.size and result.regions_read == 1
    assert provider.handles[0].closed == 1
    assert "address" not in vars(result) and "pid" not in vars(result)
    assert "ready" not in repr(result) and "fixture-sha256" not in repr(IDENTITY)


@pytest.mark.parametrize("fields", [("secret",), ("job_status", "job_status"), ()])
def test_field_scope_is_rejected_before_open(fields):
    provider = Provider()
    assert observe(provider, fields=fields) == ObservationFailure(FailureReason.SCOPE_DENIED)
    assert provider.opened == []


def test_reviewed_field_ceiling_copies_mutable_input():
    fields = ["job_status"]
    reviewed = probe(fields=fields)
    fields.append("secret")
    assert reviewed.fields == ("job_status",)
    assert observe(Provider(), reviewed, ("secret",)).reason == FailureReason.SCOPE_DENIED


@pytest.mark.parametrize("changes", [{"birth": 901}, {"session": "session-2"}, {"version": "2"},
                                     {"architecture": "arm64"}, {"executable": "different"}])
def test_retained_process_identity_must_match_before_read(changes):
    handle = Handle()
    handle.current_identity = replace(IDENTITY, **changes)
    assert observe(Provider(handle)).reason == FailureReason.TARGET_CHANGED
    assert not handle.reads and handle.closed == 1


def test_reviewed_versions_reject_before_open():
    provider = Provider()
    assert observe(provider, probe(versions=("2",))).reason == FailureReason.UNSUPPORTED
    assert not provider.opened


def test_process_identity_change_during_read_refuses_decoding():
    handle = Handle()
    handle.after_read = lambda: setattr(handle, "current_identity", replace(IDENTITY, birth=901))
    assert observe(Provider(handle)).reason == FailureReason.TARGET_CHANGED
    assert handle.closed == 1


@pytest.mark.parametrize("changes", [{"guard": True}, {"committed": False}, {"readable": False},
                                     {"size": -1}, {"base": -1}, {"readable": 1},
                                     {"allocation": True}, {"protection": -1}])
def test_invalid_regions_cannot_be_read(changes):
    handle = Handle()
    region = replace(handle.regions[0], **changes)
    handle.query_region = lambda address: region
    assert observe(Provider(handle)).reason == FailureReason.UNREADABLE_REGION
    assert not handle.reads and handle.closed == 1


def test_cross_region_reads_preserve_exact_data_and_charge_both_regions():
    handle = Handle()
    handle.regions = [MemoryRegion(ADDRESS, 4, ADDRESS, 4, True, True, False),
                      MemoryRegion(ADDRESS + 4, 12, ADDRESS + 4, 4, True, True, False)]
    result = observe(Provider(handle))
    assert result.fields == (("document_id", 17), ("job_status", "ready"))
    assert result.regions_read == 2 and result.bytes_read == 16


@pytest.mark.parametrize("limits", [{"max_bytes": 15}, {"max_regions": 1}])
def test_cumulative_budgets_stop_before_disallowed_read(limits):
    handle = Handle()
    handle.regions = [MemoryRegion(ADDRESS, 4, ADDRESS, 4, True, True, False),
                      MemoryRegion(ADDRESS + 4, 12, ADDRESS + 4, 4, True, True, False)]
    assert observe(Provider(handle), probe(**limits)).reason == FailureReason.BUDGET_EXCEEDED
    assert len(handle.reads) <= 1


def test_mapping_change_after_read_never_becomes_partial_success():
    handle = Handle()
    handle.after_read = lambda: setattr(handle, "regions", [replace(handle.regions[0], protection=2)])
    assert observe(Provider(handle)).reason == FailureReason.TARGET_CHANGED


def test_short_read_fails_and_closes():
    handle = Handle()
    handle.transform = lambda value: value[:-1]
    assert observe(Provider(handle)).reason == FailureReason.PARTIAL_READ
    assert handle.closed == 1


@pytest.mark.parametrize("address,size", [(True, 1), (1 << 64, 1), ((1 << 64) - 1, 2), (ADDRESS, 0)])
def test_invalid_private_plan_range_cannot_reach_read(address, size):
    handle = Handle()
    assert observe(Provider(handle), probe(resolve=lambda identity: ReadPlan(address, size))).reason == (
        FailureReason.UNREADABLE_REGION)
    assert not handle.reads


def test_stable_even_sequence_is_required_and_charged():
    reviewed = probe(resolve=lambda identity: ReadPlan(ADDRESS, SCHEMA.size, ADDRESS - 8))
    handle = Handle()
    result = observe(Provider(handle), reviewed)
    assert result.consistency == "sequence_checked" and result.bytes_read == 32
    handle = Handle()
    handle.after_read = lambda: handle.memory.update({ADDRESS - 8: 4})
    assert observe(Provider(handle), reviewed).reason == FailureReason.INCONSISTENT_SNAPSHOT


def test_odd_sequence_rejects_without_reading_payload():
    handle = Handle()
    handle.memory[ADDRESS - 8] = 3
    reviewed = probe(resolve=lambda identity: ReadPlan(ADDRESS, SCHEMA.size, ADDRESS - 8))
    assert observe(Provider(handle), reviewed).reason == FailureReason.INCONSISTENT_SNAPSHOT
    assert handle.reads == [(ADDRESS - 8, 8)]


def test_decode_cannot_escape_fields_or_size_bounds():
    for decoder in [lambda raw, fields: {"secret": "SECRET"},
                    lambda raw, fields: {name: "x" * 33 for name in fields}]:
        result = observe(Provider(), probe(decode=decoder))
        assert result.reason == FailureReason.DECODE_FAILED
        assert "SECRET" not in repr(result)


def test_decoder_exception_does_not_expose_memory():
    def decode_secret(raw, fields):
        raise ValueError("SECRET memory content at 0xfeed")

    result = observe(Provider(), probe(decode=decode_secret))
    assert result.reason == FailureReason.DECODE_FAILED
    assert "SECRET" not in repr(result)


@pytest.mark.parametrize("stage", ["before_open", "after_read", "decode"])
def test_cancellation_propagates_and_closes_owned_handle(stage):
    handle = Handle()
    provider = Provider(handle)
    cancelled = [stage == "before_open"]

    def checkpoint():
        if cancelled[0]:
            raise CancelledError()

    def cancel_decode(raw, fields):
        cancelled[0] = True
        return decode(raw, fields)

    if stage == "after_read":
        handle.after_read = lambda: cancelled.__setitem__(0, True)
    with pytest.raises(CancelledError):
        observe(provider, probe(decode=cancel_decode if stage == "decode" else decode), checkpoint=checkpoint)
    assert handle.closed == (0 if stage == "before_open" else 1)


@pytest.mark.parametrize("stage", ["open", "read", "decode"])
def test_one_deadline_includes_open_read_and_decode(stage):
    now = [0.0]
    handle = Handle()
    provider = Provider(handle)
    if stage == "open":
        original = provider.open_readonly

        def late_open(identity):
            now[0] = 1.0
            return original(identity)

        provider.open_readonly = late_open
    if stage == "read":
        handle.after_read = lambda: now.__setitem__(0, 1.0)

    def late_decode(raw, fields):
        if stage == "decode":
            now[0] = 1.0
        return decode(raw, fields)

    result = ProcessMemoryReader(provider, clock=lambda: now[0]).observe(
        IDENTITY, probe(decode=late_decode), ("job_status",), target_id="document")
    assert result.reason == FailureReason.DEADLINE_EXCEEDED
    assert handle.closed == 1


def test_failed_close_retains_ownership_for_retry_without_reporting_success():
    handle = Handle()
    handle.fail_close = True
    reader = ProcessMemoryReader(Provider(handle))
    result = reader.observe(IDENTITY, probe(), ("job_status",), target_id="document")
    assert result == ObservationFailure(FailureReason.CLEANUP_FAILED, retired=False)
    assert reader.pending_cleanup and not reader.close_pending()
    handle.fail_close = False
    assert reader.close_pending() and not reader.pending_cleanup


def test_cancellation_with_failed_close_retains_cleanup_for_retry():
    handle = Handle()
    handle.fail_close = True
    handle.after_read = lambda: (_ for _ in ()).throw(CancelledError())
    reader = ProcessMemoryReader(Provider(handle))
    with pytest.raises(CancelledError):
        reader.observe(IDENTITY, probe(), ("job_status",), target_id="document")
    assert reader.pending_cleanup
    handle.fail_close = False
    assert reader.close_pending()


def test_independent_readers_do_not_share_handles_or_cleanup():
    first, second = Handle(), Handle()
    first.fail_close = True
    a, b = ProcessMemoryReader(Provider(first)), ProcessMemoryReader(Provider(second))
    assert a.observe(IDENTITY, probe(), ("job_status",), target_id="a").reason == FailureReason.CLEANUP_FAILED
    assert isinstance(b.observe(IDENTITY, probe(), ("job_status",), target_id="b"), Observation)
    assert a.pending_cleanup and not b.pending_cleanup and second.closed == 1
    first.fail_close = False
    assert a.close_pending() and second.closed == 1


@pytest.mark.parametrize("changes", [{"max_bytes": True}, {"max_regions": 0}, {"timeout": float("nan")},
                                     {"timeout": float("inf")}, {"timeout": True}])
def test_invalid_reviewed_limits_are_rejected(changes):
    with pytest.raises(MemoryObservationError):
        probe(**changes)


def test_pointer_width_must_be_integer():
    with pytest.raises(MemoryObservationError):
        replace(IDENTITY, pointer_bits=64.0)


def test_decoder_output_is_snapshotted_without_retaining_mapping():
    decoded = {"job_status": "ready"}
    result = observe(Provider(), probe(decode=lambda raw, fields: decoded), ("job_status",))
    decoded["job_status"] = "SECRET"
    decoded["secret"] = "SECRET"
    assert result.fields == (("job_status", "ready"),)


@pytest.mark.parametrize("kind,reason", [(PermissionError, FailureReason.ACCESS_DENIED),
                                       (ProcessLookupError, FailureReason.TARGET_CHANGED)])
def test_provider_failure_is_sanitized_and_handle_closed(kind, reason):
    handle = Handle()

    def fail():
        raise kind("SECRET native address 0xfeed")

    handle.after_read = fail
    result = observe(Provider(handle))
    assert result.reason == reason
    assert "SECRET" not in repr(result) and "0xfeed" not in repr(result)
    assert handle.closed == 1


def test_cancellation_during_close_cannot_deliver_success():
    handle = Handle()
    cancelled = [False]
    original = handle.close

    def close():
        original()
        cancelled[0] = True

    def checkpoint():
        if cancelled[0]:
            raise CancelledError()

    handle.close = close
    with pytest.raises(CancelledError):
        observe(Provider(handle), checkpoint=checkpoint)
    assert handle.closed == 1


def test_sequence_reads_share_the_payload_budget():
    handle = Handle()
    reviewed = probe(max_bytes=31, resolve=lambda identity: ReadPlan(ADDRESS, SCHEMA.size, ADDRESS - 8))
    assert observe(Provider(handle), reviewed).reason == FailureReason.BUDGET_EXCEEDED
    assert sum(size for _, size in handle.reads) == 24


def test_query_fields_are_snapshotted_before_provider_access():
    fields = ["job_status"]
    handle = Handle()
    handle.after_read = lambda: fields.append("secret")
    result = observe(Provider(handle), fields=fields)
    assert result.fields == (("job_status", "ready"),)


def test_concurrent_operations_keep_separate_cancellation_and_handles():
    first, second = Handle(), Handle()
    reader = ProcessMemoryReader(Provider(first, second))
    entered, release = threading.Event(), threading.Event()
    interrupted = []

    def hold():
        entered.set()
        assert release.wait(3)

    def checkpoint():
        if release.is_set():
            raise CancelledError()

    def run_first():
        try:
            reader.observe(IDENTITY, probe(), ("job_status",), target_id="first", checkpoint=checkpoint)
        except CancelledError:
            interrupted.append(True)

    first.after_read = hold
    thread = threading.Thread(target=run_first)
    thread.start()
    try:
        assert entered.wait(3)
        result = reader.observe(IDENTITY, probe(), ("job_status",), target_id="second")
        assert isinstance(result, Observation)
        assert first.closed == 0 and second.closed == 1
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive() and interrupted == [True]
    assert first.closed == 1 and second.closed == 1


@pytest.mark.parametrize("boundary,reason", [("resolve", FailureReason.UNSUPPORTED),
                                           ("decode", FailureReason.DECODE_FAILED)])
def test_callback_runtime_errors_cannot_escape_private_details(boundary, reason):
    def fail(*args):
        raise RuntimeError("SECRET captured bytes at 0xfeed")

    handle = Handle()
    result = observe(Provider(handle), probe(**{boundary: fail}))
    assert result.reason == reason
    assert "SECRET" not in repr(result) and "0xfeed" not in repr(result)
    assert handle.closed == 1


@pytest.mark.parametrize("failure", [PermissionError("authority revoked"),
                                     MemoryObservationError(FailureReason.SCOPE_DENIED)])
def test_checkpoint_authority_failure_propagates_unchanged(failure):
    handle = Handle()
    calls = []

    def checkpoint():
        calls.append(True)
        if len(calls) == 2:
            raise failure

    with pytest.raises(type(failure)) as caught:
        observe(Provider(handle), checkpoint=checkpoint)
    assert caught.value is failure
    assert handle.closed == 1


@pytest.mark.parametrize("boundary", ["resolve", "decode", "read"])
@pytest.mark.parametrize("signal", [CancelledError(), AsyncCancelledError(), ExecutionStopped("test"),
                                    OperationCancelledError("test"), KeyboardInterrupt(), SystemExit()])
def test_callback_interruptions_propagate_with_original_identity(boundary, signal):
    def interrupt(*args):
        raise signal

    handle = Handle()
    reviewed = probe()
    if boundary == "read":
        handle.read = interrupt
    else:
        reviewed = probe(**{boundary: interrupt})
    with pytest.raises(type(signal)) as caught:
        observe(Provider(handle), reviewed)
    assert caught.value is signal
    assert handle.closed == 1


@pytest.mark.parametrize("boundary", ["open", "identity", "query_region", "read", "close"])
def test_unexpected_provider_failures_are_sanitized(boundary):
    def fail(*args):
        raise RuntimeError("SECRET provider bytes and address 0xfeed")

    handle = Handle()
    provider = Provider(handle)
    if boundary == "open":
        provider.open_readonly = fail
    else:
        setattr(handle, boundary, fail)
    reader = ProcessMemoryReader(provider)
    result = reader.observe(IDENTITY, probe(), ("job_status",), target_id="document")
    assert isinstance(result, ObservationFailure)
    assert "SECRET" not in repr(result) and "0xfeed" not in repr(result)
    assert result.reason == (FailureReason.CLEANUP_FAILED if boundary == "close" else FailureReason.TARGET_CHANGED)
    assert reader.pending_cleanup == (boundary == "close")
    if boundary == "close":
        handle.close = lambda: None
        assert reader.close_pending()


def test_interrupted_cleanup_retry_keeps_all_unretired_handles():
    first, second = Handle(), Handle()
    first.fail_close = second.fail_close = True
    reader = ProcessMemoryReader(Provider(first, second))
    for target in ("first", "second"):
        assert reader.observe(IDENTITY, probe(), ("job_status",), target_id=target).retired is False
    signal = CancelledError()

    def interrupt():
        raise signal

    first.close = interrupt
    with pytest.raises(CancelledError) as caught:
        reader.close_pending()
    assert caught.value is signal and reader.pending_cleanup
    first.close = lambda: None
    second.fail_close = False
    assert reader.close_pending() and not reader.pending_cleanup
    assert second.closed == 2


def test_cleanup_in_progress_still_reports_retained_ownership():
    handle = Handle()
    handle.fail_close = True
    reader = ProcessMemoryReader(Provider(handle))
    assert reader.observe(IDENTITY, probe(), ("job_status",), target_id="document").retired is False
    entered, release = threading.Event(), threading.Event()
    results = []

    def close():
        entered.set()
        assert release.wait(3)

    handle.close = close
    thread = threading.Thread(target=lambda: results.append(reader.close_pending()))
    thread.start()
    try:
        assert entered.wait(3)
        assert reader.pending_cleanup
        assert not reader.close_pending()
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive() and results == [True] and not reader.pending_cleanup
