"""Broker entry consumes owned nested bootstrap and keeps source child leases isolated."""
import os
import struct

import pytest

from je_auto_control.utils.agent_runtime import presence_broker, owner_service_nested as nested
from je_auto_control.utils.agent_runtime import owned_channel_factory as factory, helper_owner_linux
from je_auto_control.utils.agent_runtime import native_channel, owner_service_wire as wire
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from .test_agent_helper_owner_linux import FakeService


def configure(monkeypatch, data=None, *, platform='linux', binding=True):
    service = FakeService()
    if data is None:
        data = nested._FRAME.pack(nested.BOOTSTRAP_MAGIC, nested.BOOTSTRAP_VERSION,
                                 struct.pack('<QQ', *service.grant.parent[0]),
                                 struct.pack('<QQ', *service.grant.parent[1]), service.grant.capability)
    read_fd, write_fd = os.pipe()
    os.write(write_fd, data)
    os.close(write_fd)
    calls = []
    original_read = nested.read_nested_bootstrap
    def read():
        calls.append('grant')
        return original_read(read_fd)
    monkeypatch.setattr(nested, 'read_nested_bootstrap', read)
    monkeypatch.setattr(presence_broker.sys, 'platform', platform)
    monkeypatch.setattr(presence_broker, 'start_parent_watch', lambda: calls.append('watch'))
    argv = (presence_broker.sys.executable, '-u', '-m',
            'je_auto_control.utils.agent_runtime.presence_worker')
    monkeypatch.setattr(factory, 'load_binding', lambda: factory.OwnerServiceBinding('/run/owner.sock',
                       {argv: 2}) if binding else None)

    class Transport:
        def __init__(self, endpoint):
            assert endpoint == '/run/owner.sock'
        def send(self, frame):
            return service.send(frame)
        def receive(self, timeout):
            return service.receive(timeout)
        def close(self):
            calls.append('transport-close')

    monkeypatch.setattr(helper_owner_linux, 'SeqpacketTransport', Transport)
    return service, calls, read_fd


def test_entry_launches_sources_as_separate_children_of_actual_bootstrap(monkeypatch):
    service, calls, descriptor = configure(monkeypatch)
    sources = []
    def run(source, sink, broker=None):
        broker = broker if broker is not None else presence_broker.PresenceBroker()
        calls.append('run')
        sources.extend([broker._launch(), broker._launch()])
        try:
            assert sources[0].start() == {'namespace': None}
            assert sources[1].start() == {'namespace': None}
            assert service.calls.count(wire.OP_OPEN_CHILD) == 2
            assert wire.OP_OPEN_TOP not in service.calls
            assert len(service.leases) == 2
            sources[0].close()
            assert len(service.closed) == 1
            assert sources[1]._channel.request('echo', 'sibling-live', timeout=1) == 'sibling-live'
        finally:
            for child in sources:
                child.close()
    monkeypatch.setattr(presence_broker, 'run', run)
    try:
        presence_broker.main()
        assert calls[:3] == ['watch', 'grant', 'run']
        assert calls.count('grant') == 1
        assert service.closed == set(service.leases.values())
        with pytest.raises(OSError):
            os.fstat(descriptor)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def test_malformed_nested_frame_fails_before_serving_or_launching(monkeypatch):
    service, calls, descriptor = configure(monkeypatch, b'bad')
    monkeypatch.setattr(presence_broker, 'run', lambda *args: calls.append('run'))
    try:
        with pytest.raises(AgentTaskError, match='wrong length'):
            presence_broker.main()
        assert calls == ['watch', 'grant']
        assert not service.calls
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def test_nested_source_policy_refusal_has_no_local_fallback(monkeypatch):
    service, calls, descriptor = configure(monkeypatch)
    monkeypatch.setattr(factory, 'load_binding', lambda: factory.OwnerServiceBinding('/run/owner.sock', {}))
    monkeypatch.setattr(native_channel, 'OwnedChannel', lambda *args, **kwargs: pytest.fail('local fallback'))
    def run(source, sink, broker=None):
        broker = broker if broker is not None else presence_broker.PresenceBroker()
        with pytest.raises(AgentTaskError, match='no policy'):
            broker._launch().start()
    monkeypatch.setattr(presence_broker, 'run', run)
    try:
        presence_broker.main()
        assert calls == ['watch', 'grant']
        assert not service.calls
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


@pytest.mark.parametrize('platform', ['linux', 'win32'])
def test_entry_without_nested_grant_preserves_local_source(monkeypatch, platform):
    service, calls, descriptor = configure(monkeypatch, platform=platform, binding=False)
    if platform == 'linux':
        os.close(descriptor)

    class LocalChannel:
        def __init__(self, argv, **kwargs):
            assert argv[-1] == 'je_auto_control.utils.agent_runtime.presence_worker'
            calls.append('local')

        def request(self, operation, payload, **kwargs):
            assert operation == 'bootstrap'
            return {'ready': True}

        def close(self):
            calls.append('closed')

    monkeypatch.setattr(native_channel, 'OwnedChannel', LocalChannel)

    def run(source, sink, broker):
        child = broker._launch()
        try:
            assert child.start() == {'ready': True}
        finally:
            child.close()

    monkeypatch.setattr(presence_broker, 'run', run)
    try:
        presence_broker.main()
        assert calls == (['watch', 'grant'] if platform == 'linux' else ['watch']) + ['local', 'closed']
        assert not service.calls
        if platform == 'win32':
            os.fstat(descriptor)  # The Windows entry never consumes the unrelated descriptor.
    finally:
        if platform == 'win32':
            os.close(descriptor)


def test_nested_grant_without_service_never_launches_local_source(monkeypatch):
    service, calls, descriptor = configure(monkeypatch, binding=False)
    monkeypatch.setattr(native_channel, 'OwnedChannel', lambda *args, **kwargs: pytest.fail('local fallback'))

    def run(source, sink, broker):
        with pytest.raises(AgentTaskError, match='needs the Linux owner service'):
            broker._launch().start()

    monkeypatch.setattr(presence_broker, 'run', run)
    presence_broker.main()
    assert calls == ['watch', 'grant']
    assert not service.calls
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_service_rejects_forged_bootstrap_without_top_or_local_fallback(monkeypatch):
    data = nested._FRAME.pack(nested.BOOTSTRAP_MAGIC, nested.BOOTSTRAP_VERSION,
                              struct.pack('<QQ', 142, 1), struct.pack('<QQ', 0, 3), bytes(32))
    service, calls, descriptor = configure(monkeypatch, data)
    monkeypatch.setattr(native_channel, 'OwnedChannel', lambda *args, **kwargs: pytest.fail('local fallback'))

    def run(source, sink, broker):
        child = broker._launch()
        with pytest.raises(AgentTaskError, match='refused to open a lease'):
            child.start()
        child.close()

    monkeypatch.setattr(presence_broker, 'run', run)
    presence_broker.main()
    assert calls[:2] == ['watch', 'grant']
    assert wire.OP_OPEN_CHILD in service.calls
    assert wire.OP_OPEN_TOP not in service.calls
    assert not service.leases
    with pytest.raises(OSError):
        os.fstat(descriptor)
