"""A background stop that fails is kept for a retry, not only logged.

``StopQueue`` and ``stop_each`` logged a failed stop and dropped it: the
session, recorder or host might still hold its socket or device, and nothing
owned it. The application's stop custody now keeps it with its error and the
authority it was queued under, and the Diagnostics tab lists and retries it.
"""
import os

import pytest

from je_auto_control.gui._stop_custody import StopCustody, describe_stop
from je_auto_control.utils.rbac import AuthorizationContext, Role, authorization_scope
from je_auto_control.utils.rbac.authorization import current_authorization
from je_auto_control.utils.rbac.deferred import DeferredAuthorization


class _Flaky:
    """A stop that fails ``failures`` times, then succeeds; it records the caller each time."""

    def __init__(self, failures=1, message="socket busy"):
        self.failures, self.message, self.callers = failures, message, []

    def stop(self):
        caller = current_authorization()
        self.callers.append(None if caller is None else caller.user_id)
        if self.failures:
            self.failures -= 1
            raise OSError(self.message)


def test_a_held_stop_is_described_without_its_resource():
    custody, flaky = StopCustody(), _Flaky()
    stop_id = custody.hold(flaky.stop, OSError("socket busy"))
    [held] = custody.snapshot()
    assert (held.stop_id, held.label, held.error, held.attempts) == (stop_id, "_Flaky.stop", "OSError: socket busy", 1)
    assert not hasattr(held, "stop")


def test_a_retry_that_succeeds_releases_and_one_that_fails_keeps_the_new_error():
    custody, flaky = StopCustody(), _Flaky(failures=1, message="still busy")
    stop_id = custody.hold(flaky.stop, OSError("socket busy"))
    assert custody.retry(stop_id) is False
    [held] = custody.snapshot()
    assert (held.error, held.attempts) == ("OSError: still busy", 2)
    assert custody.retry(stop_id) is True
    assert custody.snapshot() == []
    assert custody.retry(stop_id) is False                   # gone: nothing to run


def test_a_retry_runs_under_the_authority_it_was_queued_with():
    custody, flaky = StopCustody(), _Flaky(failures=0)
    with authorization_scope(AuthorizationContext("operator", Role.OPERATOR)):
        authority = DeferredAuthorization.capture()
    with authorization_scope(AuthorizationContext("someone-else", Role.ADMIN)):
        stop_id = custody.hold(flaky.stop, OSError("busy"), authority=authority)
        assert custody.retry(stop_id)
    assert flaky.callers == ["operator"]


def test_forget_retry_all_and_the_limit():
    custody = StopCustody(max_held=2)
    flakies = [_Flaky(failures=0) for _ in range(3)]
    ids = [custody.hold(flaky.stop, OSError("busy")) for flaky in flakies]
    assert [held.stop_id for held in custody.snapshot()] == ids[1:]   # the oldest was let go
    assert custody.forget(ids[1]) is True and custody.forget(ids[1]) is False
    assert custody.retry_all() == (1, 0)
    assert custody.snapshot() == []


def test_listeners_hear_every_change_until_removed():
    custody, heard = StopCustody(), []
    remove = custody.add_listener(lambda: heard.append(len(custody.snapshot())))
    stop_id = custody.hold(_Flaky(failures=0).stop, OSError("busy"))
    custody.retry(stop_id)
    remove()
    custody.hold(_Flaky().stop, OSError("busy"))
    assert heard == [1, 0]


def test_a_label_names_the_stop_through_a_partial():
    import functools
    flaky = _Flaky()
    assert describe_stop(functools.partial(functools.partial(flaky.stop))) == "_Flaky.stop"


pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from je_auto_control.gui import _slow_op  # noqa: E402
from je_auto_control.gui._stop_custody import stop_custody  # noqa: E402
from headless._qt_settle import pump_until  # noqa: E402

_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def custody():
    held = stop_custody()
    for record in held.snapshot():
        held.forget(record.stop_id)
    yield held
    for record in held.snapshot():
        held.forget(record.stop_id)


def test_stop_each_runs_every_stop_and_names_each_failure():
    ran, first, second = [], _Flaky(message="first"), _Flaky(message="second")
    with pytest.raises(_slow_op.StopsFailed) as raised:
        _slow_op.stop_each(first.stop, lambda: ran.append("ok"), second.stop)
    assert ran == ["ok"]
    assert [str(error) for _stop, error in raised.value.failures] == ["first", "second"]


def test_a_stop_queue_hands_each_failed_stop_to_custody(custody):
    owner = QWidget()
    try:
        queue = _slow_op.StopQueue(owner)
        a, b, c = _Flaky(message="a"), _Flaky(message="b"), _Flaky(message="c")
        queue.retire(lambda: _slow_op.stop_each(a.stop, b.stop))     # two failures in one shutdown
        queue.retire(c.stop)
        assert pump_until(lambda: queue.pending == 0)
        held = sorted((record.label, record.error) for record in custody.snapshot())
        assert held == [("_Flaky.stop", "OSError: a"), ("_Flaky.stop", "OSError: b"), ("_Flaky.stop", "OSError: c")]
        assert custody.retry_all() == (3, 0)        # each held on its own, so each can be retried
    finally:
        owner.deleteLater()


def test_the_diagnostics_view_lists_retries_and_forgets_held_stops(custody):
    from PySide6.QtCore import Qt
    from je_auto_control.gui.failed_stops_view import FailedStopsView
    flaky, stuck = _Flaky(failures=1), _Flaky(failures=5, message="device busy")
    custody.hold(flaky.stop, OSError("socket busy"))
    custody.hold(stuck.stop, OSError("device busy"))
    view = FailedStopsView()
    try:
        assert pump_until(lambda: view._table.rowCount() == 2)
        actions = dict(view.menu_actions())
        actions["failed_stops_retry"]()              # flaky still fails once; stuck keeps failing
        assert pump_until(lambda: not view._retries.running)
        actions["failed_stops_retry"]()              # flaky is released now
        assert pump_until(lambda: not view._retries.running and view._table.rowCount() == 1)
        assert view._table.item(0, 0).data(Qt.ItemDataRole.UserRole) == custody.snapshot()[0].stop_id
        view._table.setCurrentCell(0, 0)
        actions["failed_stops_forget"]()
        assert pump_until(lambda: view._table.rowCount() == 0)
        assert custody.snapshot() == []
    finally:
        view.deleteLater()


def test_a_slow_op_stop_that_fails_is_kept_and_still_reported(custody):
    owner, reported = QWidget(), []
    try:
        op = _slow_op.SlowOp(owner)
        flaky = _Flaky(message="port still bound")
        assert op.run(flaky.stop, on_error=lambda error: reported.append(str(error)) or True, retain_failure=True)
        assert pump_until(lambda: not op.busy and bool(custody.snapshot()))
        assert [held.error for held in custody.snapshot()] == ["OSError: port still bound"]
        assert reported == ["port still bound"]              # the panel is still told
    finally:
        owner.deleteLater()


def test_a_slow_op_start_that_fails_is_not_kept(custody):
    owner = QWidget()
    try:
        op = _slow_op.SlowOp(owner)
        assert op.run(_Flaky(message="cannot bind").stop, on_error=lambda error: True)   # a start: no retain_failure
        assert pump_until(lambda: not op.busy)
        assert custody.snapshot() == []
    finally:
        owner.deleteLater()


def test_the_webrtc_host_keeps_a_session_whose_stop_failed_but_not_one_already_gone(custody):
    pytest.importorskip("aiortc", exc_type=ImportError)
    import types
    from je_auto_control.gui.remote_desktop import webrtc_host_connection, webrtc_host_sessions

    def gone():
        raise KeyError("session-1")

    failing = _Flaky(message="peer close timed out")
    webrtc_host_connection._retire_quietly(types.SimpleNamespace(stop=gone))
    webrtc_host_sessions._stop_session(types.SimpleNamespace(stop=gone))
    assert custody.snapshot() == []
    webrtc_host_sessions._stop_session(types.SimpleNamespace(stop=failing.stop))
    assert [held.error for held in custody.snapshot()] == ["OSError: peer close timed out"]


def test_an_interruption_keeps_the_owners_it_left_holding_resources(custody):
    # A cancellation that cut a media cleanup short carries the original owner;
    # only the outer stop used to be seen, and the owner's resources had no keeper.
    from je_auto_control.utils.exception.control_signals import OperationCancelledError
    from je_auto_control.utils.remote_desktop.media_retirement import preserve_interrupted_owner

    class _Owner:
        stopped = 0

        @property
        def retirement_status(self):
            return None

        def stop(self):
            _Owner.stopped += 1

    owner = _Owner()
    try:
        preserve_interrupted_owner(owner, OperationCancelledError("cancelled during unregister"))
    except OperationCancelledError as signal:
        interrupted = signal
    outer = _Flaky(failures=0)
    _slow_op.hold_failed_stop(outer.stop, interrupted)
    labels = sorted(held.label for held in custody.snapshot())
    assert labels == ["_Flaky.stop", "_Owner.stop"]
    assert custody.retry_all() == (2, 0)
    assert _Owner.stopped == 1
    _slow_op.hold_failed_stop(owner.stop, interrupted)       # the owner's own stop is not kept twice
    assert [held.label for held in custody.snapshot()] == ["_Owner.stop"]
