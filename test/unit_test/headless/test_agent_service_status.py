"""Exercise service ownership using injected functions without calling Windows."""
import ctypes
import threading

import pytest

from je_auto_control.utils.agent_runtime.service_status import ServiceFailure, ServiceQueryError, ServiceState
from je_auto_control.utils.agent_runtime.windows_service import ServiceStatusProcess, WindowsServiceStatusReader


class Function:
    def __init__(self, call):
        self.call = call
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.call(*args)


class Api:
    def __init__(self):
        self.code = 0
        self.state = 4
        self.kind = 0x10
        self.closed = []
        self.failed_close = set()
        self.OpenSCManagerW = Function(lambda *_: 101)
        self.OpenServiceW = Function(lambda *_: 202)
        self.QueryServiceStatusEx = Function(self.query)
        self.CloseServiceHandle = Function(self.close)

    def query(self, handle, level, output, size, needed):
        assert (handle, level, size) == (202, 0, 36)
        raw = ctypes.cast(output, ctypes.POINTER(ServiceStatusProcess)).contents
        raw.state, raw.service_type, raw.pid = self.state, self.kind, 777
        raw.checkpoint, raw.wait_hint, raw.controls = 9, 1500, 1
        return 1

    def close(self, handle):
        self.closed.append(handle)
        return int(handle not in self.failed_close)

    def reader(self, **kwargs):
        return WindowsServiceStatusReader("OwnedFixture", api=self, last_error=lambda: self.code, **kwargs)


def read(reader, checkpoint=lambda: None):
    return reader.read(timeout=1, checkpoint=checkpoint)


def test_lazy_local_minimal_rights_and_retained_handles():
    api = Api()
    reader = api.reader()
    assert not api.OpenSCManagerW.calls
    assert ctypes.sizeof(ServiceStatusProcess) == 36
    first = read(reader)
    api.state = 7
    assert read(reader).state is ServiceState.PAUSED
    assert first.to_dict()["consistency"] == "best_effort"
    assert first.progress_checkpoint == 9
    assert "revision" not in first.to_dict()
    assert api.OpenSCManagerW.calls == [(None, None, 1)]
    assert api.OpenServiceW.calls == [(101, "OwnedFixture", 4)]
    assert not reader.pending_cleanup
    reader.close()
    reader.close()
    assert api.closed == [202, 101]


@pytest.mark.parametrize("state", range(1, 8))
def test_states_and_diagnostic_pid(state):
    api = Api()
    api.state = state
    reader = api.reader()
    status = read(reader)
    assert status.state == state
    assert status.process_id == (777 if state >= 4 else None)
    reader.close()


@pytest.mark.parametrize("name", ["", "a/b", "a\\b", "a\0b", "a" * 257, "\ud800", "😀" * 129, None])
def test_invalid_name_never_opens(name):
    api = Api()
    with pytest.raises(ServiceQueryError) as error:
        WindowsServiceStatusReader(name, api=api, last_error=lambda: 0)
    assert error.value.reason is ServiceFailure.INVALID_REQUEST
    assert not api.OpenSCManagerW.calls


@pytest.mark.parametrize("timeout", [0, -1, 61, True, float("nan"), float("inf"), 10**1000])
def test_invalid_timeout_never_opens(timeout):
    api = Api()
    reader = api.reader()
    with pytest.raises(ServiceQueryError):
        reader.read(timeout=timeout, checkpoint=lambda: None)
    assert not api.OpenSCManagerW.calls


@pytest.mark.parametrize("point", range(1, 6))
def test_cancellation_releases_owned_handles(point):
    api = Api()
    reader = api.reader()
    calls = 0
    cancellation = RuntimeError("cancel")

    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == point:
            raise cancellation

    with pytest.raises(RuntimeError) as error:
        read(reader, checkpoint)
    assert error.value is cancellation
    assert api.closed == ([] if point == 1 else [101] if point == 2 else [202, 101])
    assert not reader.pending_cleanup
    with pytest.raises(ServiceQueryError, match="retired"):
        read(reader)


def test_cleanup_failures_remain_owned_and_do_not_replace_cancellation():
    api = Api()
    reader = api.reader()
    read(reader)
    api.failed_close = {101, 202}

    def cancel():
        raise RuntimeError("cancel")

    with pytest.raises(RuntimeError, match="cancel"):
        read(reader, cancel)
    assert reader.pending_cleanup
    assert api.closed == [202, 101]
    api.failed_close = {101}
    with pytest.raises(ServiceQueryError, match="cleanup_failed"):
        reader.close()
    api.failed_close.clear()
    reader.close()
    assert api.closed == [202, 101, 202, 101, 101]
    assert not reader.pending_cleanup


@pytest.mark.parametrize("point", range(1, 6))
def test_checkpoint_can_reenter_close_without_publishing(point):
    api = Api()
    reader = api.reader()
    calls = 0

    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == point:
            reader.close()

    with pytest.raises(ServiceQueryError, match="retired"):
        read(reader, checkpoint)
    assert len(api.QueryServiceStatusEx.calls) == int(point >= 4)
    assert not reader.pending_cleanup


@pytest.mark.parametrize("code,reason", [(5, "access_denied"), (1060, "not_found"), (122, "unavailable"),
                                         (6, "unavailable"), (1072, "unavailable"), (50, "unsupported")])
def test_open_failure_uses_fixed_reason_and_retires(code, reason):
    api = Api()
    api.code = code
    api.OpenServiceW.call = lambda *_: 0
    reader = api.reader()
    with pytest.raises(ServiceQueryError, match=f"^{reason}$"):
        read(reader)
    assert api.closed == [101]


@pytest.mark.parametrize("state,kind,reason", [(0, 16, "invalid_status"), (8, 16, "invalid_status"),
                                             (4, 1, "unsupported"), (4, 0, "unsupported")])
def test_invalid_report_retires(state, kind, reason):
    api = Api()
    api.state, api.kind = state, kind
    reader = api.reader()
    with pytest.raises(ServiceQueryError, match=reason):
        read(reader)
    assert api.closed == [202, 101]


def test_late_query_rejected():
    api = Api()
    now = [0.0]
    original = api.query

    def late(*args):
        result = original(*args)
        now[0] = 2.0
        return result

    api.QueryServiceStatusEx.call = late
    reader = api.reader(clock=lambda: now[0])
    with pytest.raises(ServiceQueryError, match="deadline_exceeded"):
        read(reader)
    assert api.closed == [202, 101]


def test_lock_admission_times_out_without_retiring_other_read():
    api = Api()
    entered, release = threading.Event(), threading.Event()
    original = api.query
    results = []

    def blocked(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    api.QueryServiceStatusEx.call = blocked
    reader = api.reader()
    worker = threading.Thread(target=lambda: results.append(read(reader)))
    worker.start()
    try:
        assert entered.wait(2)
        with pytest.raises(ServiceQueryError, match="deadline_exceeded"):
            reader.read(timeout=0.01, checkpoint=lambda: None)
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert len(results) == 1
    assert not api.closed
    reader.close()


def test_close_before_open_never_acquires():
    api = Api()
    reader = api.reader()
    reader.close()
    with pytest.raises(ServiceQueryError, match="retired"):
        read(reader)
    assert not api.OpenSCManagerW.calls


def test_reentrant_read_cannot_replace_owned_manager():
    api = Api()
    managers = iter((101, 303))
    api.OpenSCManagerW.call = lambda *_: next(managers)
    reader = api.reader()
    calls = 0

    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == 2:
            with pytest.raises(ServiceQueryError, match="busy"):
                read(reader)

    assert read(reader, checkpoint).state is ServiceState.RUNNING
    assert len(api.OpenSCManagerW.calls) == 1
    reader.close()
    assert api.closed == [202, 101]


@pytest.mark.parametrize("code", [5, 122, 6])
def test_failed_query_is_not_retried(code):
    api = Api()
    api.code = code
    api.QueryServiceStatusEx.call = lambda *_: 0
    reader = api.reader()
    with pytest.raises(ServiceQueryError):
        read(reader)
    assert len(api.QueryServiceStatusEx.calls) == 1
    assert api.closed == [202, 101]


def test_native_exception_does_not_expose_message():
    api = Api()

    def fail(*_):
        raise OSError("private service details")

    api.QueryServiceStatusEx.call = fail
    reader = api.reader()
    with pytest.raises(ServiceQueryError, match="^unavailable$") as error:
        read(reader)
    assert error.value.__suppress_context__
    assert api.closed == [202, 101]


@pytest.mark.parametrize("handle", [0, -1, 2**100, True, (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1])
def test_invalid_handle_never_used(handle):
    api = Api()
    api.OpenServiceW.call = lambda *_: handle
    reader = api.reader()
    with pytest.raises(ServiceQueryError, match="unavailable"):
        read(reader)
    assert not api.QueryServiceStatusEx.calls
    assert api.closed == [101]


def test_concurrent_close_rejects_late_query():
    api = Api()
    entered, release, retiring = threading.Event(), threading.Event(), threading.Event()
    outcomes = []
    original = api.query
    reader = api.reader()

    def blocked(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    def query():
        try:
            outcomes.append(read(reader))
        except ServiceQueryError as error:
            outcomes.append(error.reason)

    def close():
        retiring.set()
        reader.close()

    api.QueryServiceStatusEx.call = blocked
    worker = threading.Thread(target=query)
    closer = threading.Thread(target=close)
    worker.start()
    try:
        assert entered.wait(2)
        closer.start()
        assert retiring.wait(2)
        # Observe retirement before releasing the injected syscall, without timing guesses.
        assert reader._retired.wait(2)
    finally:
        release.set()
        worker.join(3)
        if closer.ident is not None:
            closer.join(3)
    assert not worker.is_alive() and not closer.is_alive()
    assert outcomes == [ServiceFailure.RETIRED]
    assert api.closed == [202, 101]
