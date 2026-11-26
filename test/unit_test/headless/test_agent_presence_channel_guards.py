"""Linux and macOS transports never widen presence gates, and one bad connector never fails a listener."""
import sys
import threading
from unittest import mock

import pytest

from je_auto_control.utils.agent_runtime import activity, presence_host
from je_auto_control.utils.agent_runtime import presence_channel_darwin as channel_darwin
from je_auto_control.utils.agent_runtime import presence_channel_linux as channel_linux
from je_auto_control.utils.agent_runtime import presence_pipe_linux as pipe_linux
from je_auto_control.utils.agent_runtime.errors import AgentControlBusy, AgentTaskError, PresencePeerRefused
from je_auto_control.utils.agent_runtime.presence_channel_darwin import DarwinListener
from je_auto_control.utils.agent_runtime.presence_channel_linux import LinuxChannel, LinuxListener
from je_auto_control.utils.agent_runtime.presence_peer_linux import _RetirementUnconfirmed


@pytest.mark.parametrize('platform', ['linux', 'darwin', 'freebsd'])
def test_transport_types_do_not_enable_non_windows_presence_or_input(monkeypatch, platform):
    assert LinuxChannel.connect
    assert LinuxListener.create
    monkeypatch.setattr(sys, 'platform', platform)
    with pytest.raises(AgentControlBusy, match='Windows console session'):
        presence_host.require_windows()
    with pytest.raises(AgentControlBusy, match='trusted platform adapter'):
        activity.desktop_activity_gate(lambda: pytest.fail('takeover callback must remain inert'))


class FakeListeningSocket:
    """Hands out queued connections, or raises a queued accept failure."""

    def __init__(self, *accepted):
        self.accepted = list(accepted)

    def accept(self):
        item = self.accepted.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item, None


class FakeListenerResources:
    def __init__(self, *accepted):
        self.connection = FakeListeningSocket(*accepted)
        self.closed = False

    def close(self):
        self.closed = True


class FakeChannel:
    def __init__(self, connection):
        self.connection, self.closed = connection, False

    def close(self):
        self.closed = True


def fake_listener(monkeypatch, cls, *accepted):
    """A real listener type and lease owner over a fake listening socket, with readiness always true."""
    monkeypatch.setattr(channel_linux._Owner, 'ready', lambda *_arguments, **_keywords: None)
    listener = object.__new__(cls)
    resources = FakeListenerResources(*accepted)
    listener._owner = channel_linux._Owner(resources)
    return listener, resources


def capture_refusing(*refused):
    def capture(connection):
        if connection in refused:
            raise AgentTaskError('connected-peer process has retired or was replaced')
        return FakeChannel(connection)
    return capture


@pytest.mark.parametrize('module, cls', [(channel_linux, LinuxListener), (channel_darwin, DarwinListener)])
def test_a_refused_or_vanished_peer_fails_only_its_own_connection(monkeypatch, module, cls):
    gone, bad, good = object(), object(), object()
    listener, resources = fake_listener(monkeypatch, cls, ConnectionAbortedError(), bad, gone, good)
    monkeypatch.setattr(module, '_capture', capture_refusing(bad, gone))
    for _refused in (bad, gone):
        with pytest.raises(PresencePeerRefused):
            listener.accept(timeout=1)
        assert isinstance(listener._owner._state, channel_linux._Open) and not resources.closed
    channel = listener.accept(timeout=1)
    assert channel.connection is good and not channel.closed


@pytest.mark.parametrize('module, cls', [(channel_linux, LinuxListener), (channel_darwin, DarwinListener)])
def test_an_accepted_socket_that_did_not_confirm_retirement_still_revokes_the_listener(monkeypatch, module, cls):
    listener, resources = fake_listener(monkeypatch, cls, object())
    monkeypatch.setattr(module, '_capture', mock.Mock(side_effect=_RetirementUnconfirmed('unconfirmed')))
    with pytest.raises(_RetirementUnconfirmed):
        listener.accept(timeout=1)
    assert isinstance(listener._owner._state, channel_linux._Retired) and listener._owner._state.unconfirmed
    assert resources.closed


@pytest.mark.parametrize('module, cls', [(channel_linux, LinuxListener), (channel_darwin, DarwinListener)])
def test_a_cancelled_accept_closes_the_channel_it_captured(monkeypatch, module, cls):
    listener, _resources = fake_listener(monkeypatch, cls, object())
    cancel, captured = threading.Event(), []

    def capture(connection):
        cancel.set()
        captured.append(FakeChannel(connection))
        return captured[-1]
    monkeypatch.setattr(module, '_capture', capture)
    with pytest.raises(AgentTaskError, match='cancelled'):
        listener.accept(timeout=1, cancel=cancel)
    assert captured[0].closed


def test_the_presence_listener_keeps_waiting_past_a_refused_peer(monkeypatch):
    monkeypatch.setattr(pipe_linux, '_wait_readable', lambda descriptor, cancel: None)
    inner = mock.Mock()
    inner.fileno.return_value = 3
    inner.accept.side_effect = [PresencePeerRefused('refused'), FakeChannel('good')]
    connection = pipe_linux.LinuxPresenceListener(inner).accept()
    assert isinstance(connection, pipe_linux.LinuxBytePipe) and inner.accept.call_count == 2
    inner.accept.side_effect = [AgentTaskError('listener retired')]
    with pytest.raises(AgentTaskError, match='retired'):
        pipe_linux.LinuxPresenceListener(inner).accept()
