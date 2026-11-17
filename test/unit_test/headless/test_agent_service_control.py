"""Verify service controls with injected APIs, never the system service manager."""
import ctypes
from dataclasses import replace
import threading

import pytest

from je_auto_control.utils.agent_runtime.errors import AgentEffectUnknown, AgentObservationStale, AgentTaskError
from je_auto_control.utils.agent_runtime.service_operations import ServiceOperation
from je_auto_control.utils.agent_runtime.service_status import ServiceQueryError
from je_auto_control.utils.agent_runtime.windows_service import WindowsServiceController, WindowsServiceStatusReader
from je_auto_control.utils.agent_runtime.windows_service_native import ServiceControlStatus
from .test_agent_service_status import Api, Function, read

START, STOP = ServiceOperation.START, ServiceOperation.STOP


class ControlApi(Api):
    def __init__(self):
        super().__init__()
        self.StartServiceW = Function(lambda *_: 1)
        self.ControlService = Function(self.stop)

    def stop(self, handle, control, output):
        assert (handle, control) == (202, 1)
        assert ctypes.sizeof(output._obj) == 28
        ctypes.cast(output, ctypes.POINTER(ServiceControlStatus)).contents.state = 1
        return 1

    def controller(self, allowed=frozenset({START, STOP}), **kwargs):
        return WindowsServiceController("OwnedFixture", allowed=allowed, api=self,
                                        last_error=lambda: self.code, **kwargs)


def perform(controller, operation, expected, ident="journal-1", checkpoint=lambda: None):
    return controller.perform(operation, expected=expected, operation_id=ident, timeout=1, checkpoint=checkpoint)


@pytest.mark.parametrize("allowed,access", [(frozenset({START}), 0x14), (frozenset({STOP}), 0x24),
                                           (frozenset({START, STOP}), 0x34)])
def test_minimal_control_rights(allowed, access):
    api = ControlApi()
    controller = api.controller(allowed)
    assert not api.OpenSCManagerW.calls
    read(controller)
    assert api.OpenServiceW.calls == [(101, "OwnedFixture", access)]
    assert hasattr(api.StartServiceW, "argtypes") == (START in allowed)
    assert hasattr(api.ControlService, "argtypes") == (STOP in allowed)
    controller.close()


def test_readonly_facade_never_binds_controls():
    api = Api()
    reader = WindowsServiceStatusReader("OwnedFixture", api=api, last_error=lambda: 0)
    assert not hasattr(reader, "perform")
    read(reader)
    assert api.OpenServiceW.calls[-1][-1] == 4
    reader.close()


@pytest.mark.parametrize("allowed", [frozenset(), {START}, frozenset({"start"}), None])
def test_invalid_host_scope_acquires_nothing(allowed):
    api = ControlApi()
    with pytest.raises(AgentTaskError):
        api.controller(allowed)
    assert not api.OpenSCManagerW.calls


def test_start_acceptance_is_not_readback_and_replay_never_dispatches():
    api = ControlApi()
    api.state = 1
    controller = api.controller()
    before = read(controller)
    receipt = perform(controller, START, before)
    assert receipt.accepted and receipt.comparison == "non_atomic"
    assert not hasattr(receipt, "completed")
    assert api.StartServiceW.calls == [(202, 0, None)]
    assert perform(controller, START, before) == receipt
    assert read(controller).state == 1
    with pytest.raises(AgentTaskError, match="readback"):
        perform(controller, START, before, "journal-2")
    api.state = 4
    running = read(controller)
    assert perform(controller, STOP, running, "journal-2").accepted
    assert len(api.OpenServiceW.calls) == 1
    assert len(api.ControlService.calls) == 1
    controller.close()


def test_stop_return_buffer_is_not_independent_readback():
    api = ControlApi()
    controller = api.controller()
    before = read(controller)
    receipt = perform(controller, STOP, before)
    assert receipt.accepted
    assert read(controller).state == 4
    with pytest.raises(AgentTaskError, match="readback"):
        perform(controller, STOP, before, "journal-2")
    api.state = 1
    stopped = read(controller)
    assert perform(controller, START, stopped, "journal-2").accepted
    controller.close()


@pytest.mark.parametrize("operation,state", [(START, 4), (START, 2), (STOP, 1), (STOP, 2), (STOP, 3), (STOP, 5)])
def test_precondition_refuses_without_native_control(operation, state):
    api = ControlApi()
    api.state = state
    controller = api.controller()
    before = read(controller)
    with pytest.raises(AgentTaskError, match="does not permit"):
        perform(controller, operation, before)
    assert not api.StartServiceW.calls and not api.ControlService.calls
    controller.close()


def test_changed_status_refuses_and_does_not_consume_id():
    api = ControlApi()
    api.state = 1
    controller = api.controller()
    before = read(controller)
    api.state = 4
    with pytest.raises(AgentObservationStale):
        perform(controller, START, before)
    assert not api.StartServiceW.calls
    api.state = 1
    assert perform(controller, START, before).accepted
    controller.close()


def test_only_host_granted_control_can_dispatch():
    api = ControlApi()
    api.state = 1
    controller = api.controller(frozenset({STOP}))
    with pytest.raises(AgentTaskError, match="host scope"):
        perform(controller, START, read(controller))
    assert not api.StartServiceW.calls
    controller.close()


def test_paused_stop_supported_but_missing_stop_bit_refused():
    api = ControlApi()
    api.state = 7
    controller = api.controller()
    before = read(controller)
    original = api.query

    def no_stop(*args):
        result = original(*args)
        args[2]._obj.controls = 0
        return result

    api.QueryServiceStatusEx.call = no_stop
    with pytest.raises(AgentTaskError, match="does not permit"):
        perform(controller, STOP, read(controller))
    api.QueryServiceStatusEx.call = original
    assert perform(controller, STOP, before).accepted
    controller.close()


@pytest.mark.parametrize("field,value", [("state", 1), ("controls_accepted", True), ("process_id", False),
                                       ("wait_hint_ms", -1), ("progress_checkpoint", 2**32)])
def test_forged_status_refused_before_control(field, value):
    api = ControlApi()
    api.state = 1
    controller = api.controller()
    before = replace(read(controller), **{field: value})
    with pytest.raises(AgentTaskError):
        perform(controller, START, before)
    assert not api.StartServiceW.calls
    controller.close()


@pytest.mark.parametrize("ident", ["", "a" * 129, "a\n", True, None])
def test_invalid_id_refused(ident):
    api = ControlApi()
    api.state = 1
    controller = api.controller()
    before = read(controller)
    with pytest.raises(AgentTaskError):
        perform(controller, START, before, ident)
    assert not api.StartServiceW.calls
    controller.close()


@pytest.mark.parametrize("failure", [0, OSError("private native error")])
def test_failed_native_control_stays_unknown_after_readback(failure):
    api = ControlApi()
    api.state, api.code = 1, 1053
    controller = api.controller()
    before = read(controller)

    def fail(*_):
        api.state = 4
        if isinstance(failure, Exception):
            raise failure
        return failure

    api.StartServiceW.call = fail
    with pytest.raises(AgentEffectUnknown):
        perform(controller, START, before)
    running = read(controller)
    assert running.state == 4
    with pytest.raises(AgentEffectUnknown):
        perform(controller, START, before)
    with pytest.raises(AgentEffectUnknown):
        perform(controller, STOP, running, "journal-2")
    assert len(api.StartServiceW.calls) == 1
    assert not api.ControlService.calls
    controller.close()


def test_post_dispatch_cancellation_preserved_but_never_replayed():
    api = ControlApi()
    api.state = 1
    controller = api.controller()
    before = read(controller)
    cancellation = RuntimeError("cancel")

    def checkpoint():
        if api.StartServiceW.calls:
            raise cancellation

    with pytest.raises(RuntimeError) as error:
        perform(controller, START, before, checkpoint=checkpoint)
    assert error.value is cancellation
    with pytest.raises(AgentEffectUnknown):
        perform(controller, START, before)
    controller.close()


def test_post_dispatch_deadline_is_unknown():
    api = ControlApi()
    api.state = 1
    now = [0.0]
    controller = api.controller(clock=lambda: now[0])
    before = read(controller)

    def late(*_):
        now[0] = 2
        return 1

    api.StartServiceW.call = late
    with pytest.raises(AgentEffectUnknown):
        perform(controller, START, before)
    assert read(controller).state == 1
    with pytest.raises(AgentEffectUnknown):
        perform(controller, START, before)
    controller.close()


def test_conflicting_replay_and_bounded_non_evicting_ledger():
    api = ControlApi()
    api.state = 1
    controller = api.controller()
    original = read(controller)
    first = perform(controller, START, original, "journal-0")
    with pytest.raises(AgentTaskError, match="conflicts"):
        perform(controller, STOP, original, "journal-0")
    for index in range(1, 64):
        api.state = 4 if index % 2 else 1
        before = read(controller)
        perform(controller, STOP if index % 2 else START, before, f"journal-{index}")
    api.state = 1
    before = read(controller)
    with pytest.raises(AgentTaskError, match="full"):
        perform(controller, START, before, "journal-64")
    assert perform(controller, START, original, "journal-0") == first
    assert len(api.StartServiceW.calls) + len(api.ControlService.calls) == 64
    controller.close()


def test_reentrant_controls_are_rejected_without_overwriting_ledger():
    api = ControlApi()
    api.state = 1
    controller = api.controller()
    before = read(controller)

    def checkpoint():
        with pytest.raises(ServiceQueryError, match="busy"):
            perform(controller, START, before, "nested")

    perform(controller, START, before, checkpoint=checkpoint)
    assert len(api.StartServiceW.calls) == 1
    controller.close()


def test_concurrent_close_during_control_leaves_unknown_effect():
    api = ControlApi()
    api.state = 1
    controller = api.controller()
    before = read(controller)
    entered, release = threading.Event(), threading.Event()
    results = []

    def blocked(*_):
        entered.set()
        assert release.wait(3)
        return 1

    def work():
        try:
            results.append(perform(controller, START, before))
        except AgentEffectUnknown:
            results.append("unknown")

    api.StartServiceW.call = blocked
    worker = threading.Thread(target=work)
    closer = threading.Thread(target=controller.close)
    worker.start()
    try:
        assert entered.wait(2)
        closer.start()
        assert controller._session._retired.wait(2)
    finally:
        release.set()
        worker.join(3)
        if closer.ident is not None:
            closer.join(3)
    assert not worker.is_alive() and not closer.is_alive()
    assert results == ["unknown"]
    assert api.closed == [202, 101]


@pytest.mark.parametrize("clock_after_call", [1, 2])
def test_reentrant_clock_close_cannot_publish_acceptance(clock_after_call):
    api = ControlApi()
    api.state = 1
    checks = 0
    controller = None

    def clock():
        nonlocal checks
        if api.StartServiceW.calls:
            checks += 1
            if checks == clock_after_call:
                controller.close()
        return 0.0

    controller = api.controller(clock=clock)
    before = read(controller)
    with pytest.raises(AgentEffectUnknown):
        perform(controller, START, before)
    assert api.closed == [202, 101]


def test_cached_acceptance_clock_close_cannot_publish():
    api = ControlApi()
    api.state = 1
    replay_clocks = [None]
    controller = None

    def clock():
        if replay_clocks[0] is not None:
            replay_clocks[0] += 1
            if replay_clocks[0] == 4:
                controller.close()
        return 0.0

    controller = api.controller(clock=clock)
    before = read(controller)
    perform(controller, START, before)
    replay_clocks[0] = 0
    with pytest.raises(ServiceQueryError, match="retired"):
        perform(controller, START, before)
    assert len(api.StartServiceW.calls) == 1
    assert replay_clocks[0] == 4


@pytest.mark.parametrize("perform_control,publication_clock", [(True, 8), (False, 6)])
def test_retirement_at_reservation_or_read_publication(perform_control, publication_clock):
    api = ControlApi()
    api.state = 1
    admission_clocks = [None]
    controller = None

    def clock():
        if admission_clocks[0] is not None:
            admission_clocks[0] += 1
            if admission_clocks[0] == publication_clock:
                controller.close()
        return 0.0

    controller = api.controller(clock=clock)
    before = read(controller)
    admission_clocks[0] = 0
    with pytest.raises(ServiceQueryError, match="retired"):
        if perform_control:
            perform(controller, START, before)
        else:
            read(controller)
    assert admission_clocks[0] == publication_clock
    assert not api.StartServiceW.calls
    assert api.closed == [202, 101]
    assert not controller.pending_cleanup
