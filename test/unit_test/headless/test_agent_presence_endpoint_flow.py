"""Owned endpoint metadata survives private host transport without widening source leases."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.presence_host import TargetPresence
from .test_agent_presence_pool import Channel, noop, pool
from .test_agent_presence_broker import setup, Child


@pytest.fixture
def endpoint(tmp_path):
    return {'directory': str(tmp_path), 'socket_name': 'source.sock',
            'directory_identity': {'device': 1, 'inode': 2, 'owner': 3, 'mode': 448},
            'socket_identity': {'device': 1, 'inode': 4, 'owner': 3, 'mode': 384},
            'listener_process': {'pid': 5, 'uid': 3, 'gid': 3, 'birth': 6,
                                 'user_namespace': 'user:[7]', 'pid_namespace': 'pid:[8]'}}


class EndpointChannel(Channel):
    def __init__(self, endpoint):
        super().__init__()
        self.endpoint = endpoint

    def request(self, operation, body, **kwargs):
        result = super().request(operation, body, **kwargs)
        if operation == 'bootstrap':
            result['endpoint'] = self.endpoint
        return result


def test_pool_snapshots_endpoint_for_only_exact_live_owned_lease(endpoint):
    original = deepcopy(endpoint)
    channel = EndpointChannel(endpoint)
    instance = pool(lambda argv: channel)
    first, other = instance.reference(), instance.reference()
    try:
        binding = first.acquire(noop, 2)
        endpoint['listener_process']['pid'] = 999
        assert first.endpoint(binding) == original
        result = first.endpoint(binding)
        result['socket_identity']['inode'] = 999
        assert first.endpoint(binding) == original
        with pytest.raises(AgentTaskError):
            other.endpoint(binding)
        with pytest.raises(AgentTaskError):
            first.endpoint({**binding, 'generation': 'wrong'})
        first.release(binding)
        with pytest.raises(AgentTaskError):
            first.endpoint(binding)
        assert all('endpoint' not in body for operation, body in channel.calls)
    finally:
        first.close()
        other.close()
    with pytest.raises(AgentTaskError):
        first.endpoint(binding)


def test_target_pins_owned_endpoint_and_returns_copies(endpoint):
    instance = pool(lambda argv: EndpointChannel(endpoint))
    reference = instance.reference()
    operation = SimpleNamespace(presence=lambda: reference, checkpoint=noop, spec=object())
    channel = object()
    target = TargetPresence()
    try:
        binding = target.bind(operation, channel, 2)
        result = target.endpoint()
        result['listener_process']['pid'] = 900
        assert target.endpoint() == endpoint
        assert target.bind(operation, channel, 2) == binding
        with pytest.raises(AgentTaskError):
            target.bind(operation, object(), 2)
        reference.release(binding)
        with pytest.raises(AgentTaskError):
            target.bind(operation, channel, 2)
    finally:
        reference.close()
        target.release()


def test_broker_publishes_only_owned_validated_endpoint_after_handshake(endpoint, monkeypatch):
    create, source, pipe, children = setup(monkeypatch)
    real_start = Child.start
    def start(child):
        result = real_start(child)
        result['endpoint'] = endpoint
        return result
    monkeypatch.setattr(Child, 'start', start)
    pipe.use = lambda value: None
    broker = create()
    try:
        result = broker.bootstrap()
        assert result['endpoint'] == endpoint
        original = deepcopy(endpoint)
        endpoint['listener_process']['pid'] = 100
        result['endpoint']['socket_identity']['inode'] = 100
        assert broker.bootstrap()['endpoint'] == original
    finally:
        broker.close()


@pytest.mark.parametrize('replacement', [None, {}, {'ready': True}])
def test_pool_rejects_malformed_owned_endpoint(replacement):
    instance = pool(lambda argv: EndpointChannel(replacement))
    reference = instance.reference()
    try:
        with pytest.raises(AgentTaskError):
            reference.acquire(noop, 2)
    finally:
        reference.close()


def test_worker_rejects_changed_removed_or_added_endpoint(endpoint, monkeypatch):
    from je_auto_control.utils.agent_runtime.native_worker import NativeWorker
    worker = NativeWorker(None, None, target=object())
    monkeypatch.setattr(worker, '_requires_presence', lambda: True)
    channel = EndpointChannel(endpoint)
    binding = channel.protocol.request({'request_id': 1, 'operation': 'acquire', 'body': {}})['result']
    try:
        worker._configure_presence({'presence': binding, 'presence_endpoint': endpoint})
        worker._check_presence_pin(None, None, {'presence': binding, 'presence_endpoint': deepcopy(endpoint)})
        for changed in [None, {}, {**endpoint, 'socket_name': 'other.sock'}]:
            with pytest.raises(AgentTaskError):
                worker._check_presence_pin(None, None, {'presence': binding, 'presence_endpoint': changed})
        worker._presence_endpoint = None
        with pytest.raises(AgentTaskError):
            worker._check_presence_pin(None, None, {'presence': binding, 'presence_endpoint': endpoint})
    finally:
        channel.close()


def test_reader_uses_private_endpoint_before_connect_and_keeps_windows_gate(endpoint, monkeypatch):
    from je_auto_control.utils.agent_runtime import presence_reader
    from je_auto_control.utils.agent_runtime.presence_pipe_linux import LinuxPresencePipe
    channel = EndpointChannel(endpoint)
    binding = channel.protocol.request({'request_id': 1, 'operation': 'acquire', 'body': {}})['result']
    try:
        monkeypatch.setattr(presence_reader.sys, 'platform', 'linux')
        reader = presence_reader.PresenceReader(binding, noop)
    except AgentTaskError as error:
        assert 'owned launch endpoint' in str(error)
    else:
        pytest.fail('Linux reader accepted missing endpoint')
    try:
        reader = presence_reader.PresenceReader(binding, noop, endpoint=endpoint)
        assert isinstance(reader._wire.pipe, LinuxPresencePipe)
        assert reader._wire.pipe._endpoint.socket_name == endpoint['socket_name']
        endpoint['socket_name'] = 'changed.sock'
        assert reader._wire.pipe._endpoint.socket_name == 'source.sock'
        reader.close()
        monkeypatch.setattr(presence_reader.sys, 'platform', 'win32')
        with pytest.raises(AgentTaskError, match='unsupported'):
            presence_reader.PresenceReader(binding, noop, endpoint=endpoint)
    finally:
        channel.close()


@pytest.mark.parametrize('bad_endpoint', [False, True])
def test_broker_does_not_publish_unverified_owned_endpoint(endpoint, monkeypatch, bad_endpoint):
    from je_auto_control.utils.agent_runtime import presence_broker
    create, source, pipe, children = setup(monkeypatch)
    real_start = Child.start
    def start(child):
        result = real_start(child)
        result['endpoint'] = {} if bad_endpoint else endpoint
        return result
    monkeypatch.setattr(Child, 'start', start)
    if not bad_endpoint:
        monkeypatch.setattr(presence_broker, 'client_handshake',
                            lambda conn, security: ('wrong-generation', SimpleNamespace(close=noop)))
    pipe.use = lambda value: None
    broker = create()
    with pytest.raises(AgentTaskError):
        broker.bootstrap()
    assert children[0].closed
    assert broker._binding.closed


def test_windows_bootstrap_and_reference_do_not_add_endpoint(monkeypatch):
    instance = pool(lambda argv: Channel())
    reference = instance.reference()
    try:
        binding = reference.acquire(noop, 2)
        assert reference.endpoint(binding) is None
    finally:
        reference.close()



def test_runtime_configure_carries_only_host_endpoint_to_worker(endpoint, tmp_path, monkeypatch):
    import io
    from .test_agent_presence_runtime import Fixture, spec
    from .test_agent_presence_binding import Target, Gate
    from je_auto_control.utils.agent_runtime import native_worker
    fixture = Fixture(monkeypatch, tmp_path)
    fixture.source = EndpointChannel(endpoint)
    captured = []

    class Reader(Gate):
        def __init__(self, binding, takeover, *, endpoint):
            super().__init__(binding, takeover)
            captured.append(deepcopy(endpoint))

    monkeypatch.setattr(native_worker, 'DesktopTarget', Target)
    monkeypatch.setattr(native_worker, 'PresenceReader', Reader)
    runtime = fixture.runtime('endpoint')
    worker = native_worker.NativeWorker(io.BytesIO(), io.BytesIO())
    try:
        request = spec()
        request['options'] = {'presence_endpoint': {'untrusted': True}}
        task = runtime.submit(request)
        runtime.observe(task.task_id)
        payload = next(payload for operation, payload, timeout in fixture.helpers[0].calls
                       if operation == 'configure')
        assert payload['presence_endpoint'] == endpoint
        assert worker._dispatch('configure', payload)['ready']
        assert captured == [endpoint]
        changed = deepcopy(payload)
        changed['presence_endpoint']['socket_name'] = 'different.sock'
        with pytest.raises(AgentTaskError):
            worker._dispatch('configure', changed)
    finally:
        worker.close()
        runtime.close()
