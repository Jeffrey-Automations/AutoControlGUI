"""LAN browser cleanup observes fake threads and denies retired publications."""
import threading
from types import SimpleNamespace

import pytest

from je_auto_control.utils.exception.control_signals import OperationCancelledError
from je_auto_control.utils.remote_desktop import lan_discovery as discovery
from je_auto_control.utils.remote_desktop.media_retirement import (
    Completion, MediaRetirementError, interrupted_retirement_owners,
)


@pytest.fixture
def backend(monkeypatch):
    calls = []

    class Zeroconf:
        close_failures = 0

        def close(self):
            calls.append('close')
            if self.close_failures:
                self.close_failures -= 1
                raise OSError('fake close failure')

    class Browser:
        def __init__(self, zc, kind, listener):
            self.listener = listener
            self.alive = True
            self.failure = None

        def cancel(self):
            calls.append('cancel')
            if self.failure is not None:
                raise self.failure
            self.alive = False

        def is_alive(self):
            return self.alive

    monkeypatch.setattr(discovery, '_AVAILABLE', True)
    monkeypatch.setattr(discovery, 'Zeroconf', Zeroconf)
    monkeypatch.setattr(discovery, 'ServiceBrowser', Browser)
    return SimpleNamespace(calls=calls, Zeroconf=Zeroconf)


def notify(owner):
    owner._listener.remove_service(None, 'fake', 'late')


def test_cancel_failure_retains_original_browser_and_never_replays_cancel(backend):
    published = []
    owner = discovery.HostBrowser(published.append)
    browser = owner._browser
    browser.failure = OSError('fake cancellation failure')
    with pytest.raises(MediaRetirementError) as failure:
        owner.stop()
    assert failure.value.owner is owner
    assert owner._browser is browser
    assert backend.calls == ['cancel', 'close']
    notify(owner)
    assert published == []
    with pytest.raises(MediaRetirementError):
        owner.stop()
    assert backend.calls == ['cancel', 'close']
    browser.alive = False
    owner.stop()
    assert owner.retirement_status.complete
    assert backend.calls == ['cancel', 'close']


def test_retry_only_repeats_documented_idempotent_close(backend):
    owner = discovery.HostBrowser(lambda _: None)
    owner._zc.close_failures = 1
    with pytest.raises(MediaRetirementError) as failure:
        owner.stop()
    assert failure.value.status.retryable
    owner.stop()
    owner.stop()
    assert backend.calls == ['cancel', 'close', 'close']
    assert owner.retirement_status.complete


def test_in_flight_publication_stays_owned_without_blocking_or_closing_its_resources(backend):
    entered, release = threading.Event(), threading.Event()

    def callback(_):
        entered.set()
        assert release.wait(3)

    owner = discovery.HostBrowser(callback)
    thread = threading.Thread(target=notify, args=(owner,))
    thread.start()
    try:
        assert entered.wait(3)
        with pytest.raises(MediaRetirementError) as failure:
            owner.stop()
        assert failure.value.status.resources is Completion.PENDING
        assert backend.calls == []
    finally:
        release.set()
        thread.join(3)
    owner.stop()
    assert owner.retirement_status.complete


def test_callback_reentrant_stop_does_not_join_itself(backend):
    observed = []

    def callback(_):
        with pytest.raises(MediaRetirementError) as failure:
            owner.stop()
        observed.append(failure.value.status)

    owner = discovery.HostBrowser(callback)
    notify(owner)
    assert len(observed) == 1 and observed[0].retryable
    assert backend.calls == []
    owner.stop()
    assert owner.retirement_status.complete


@pytest.mark.parametrize('interrupted', [False, True])
def test_failed_browser_constructor_keeps_acquisition_uncertainty_and_close_owner(backend, monkeypatch, interrupted):
    backend.Zeroconf.close_failures = 1
    original = OperationCancelledError('test') if interrupted else OSError('partial constructor')

    def failed(*args, **kwargs):
        raise original

    monkeypatch.setattr(discovery, 'ServiceBrowser', failed)
    with pytest.raises(type(original) if interrupted else MediaRetirementError) as caught:
        discovery.HostBrowser(lambda _: None)
    if interrupted:
        assert caught.value is original
        (owner,) = interrupted_retirement_owners(original)
    else:
        owner = caught.value.owner
    assert owner.retirement_status.retryable
    with pytest.raises(MediaRetirementError):
        owner.stop()
    assert backend.calls == ['close', 'close']
    assert owner.retirement_status.resources is Completion.UNCERTAIN
    assert not owner.retirement_status.retryable


def test_interruption_preserves_identity_after_independent_close(backend):
    owner = discovery.HostBrowser(lambda _: None)
    signal = OperationCancelledError('original')
    wrapped = OSError('wrapper')
    wrapped.__cause__ = signal
    owner._browser.failure = wrapped
    with pytest.raises(OperationCancelledError) as caught:
        owner.stop()
    assert caught.value is signal
    assert interrupted_retirement_owners(signal) == (owner,)
    assert backend.calls == ['cancel', 'close']


def test_one_shot_interruption_retains_browser_when_cleanup_fails(backend, monkeypatch):
    signal = OperationCancelledError('browse interrupted')
    backend.Zeroconf.close_failures = 1

    class InterruptedWait:
        def wait(self, timeout):
            raise signal

    monkeypatch.setattr(discovery, 'threading', SimpleNamespace(
        Lock=threading.Lock, Event=InterruptedWait,
    ))
    with pytest.raises(OperationCancelledError) as caught:
        discovery.list_local_services()
    assert caught.value is signal
    (owner,) = interrupted_retirement_owners(signal)
    assert not owner.retirement_status.complete
    assert backend.calls == ['cancel', 'close']
    owner.stop()
    assert owner.retirement_status.complete
    assert backend.calls == ['cancel', 'close', 'close']
