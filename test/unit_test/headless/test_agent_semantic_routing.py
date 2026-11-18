"""Exercise semantic proxy routing through the real factory without native processes."""
from types import SimpleNamespace

import pytest

from je_auto_control.utils.agent_runtime import helper_owner_linux, native_channel
from je_auto_control.utils.agent_runtime import owned_channel_factory as factory
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.context import TaskOperation, operation_scope
from je_auto_control.utils.agent_runtime.models import AgentTaskSpec
from je_auto_control.utils.agent_runtime.native_target import NativeDesktopTarget
from je_auto_control.utils.agent_runtime.semantic_native_target import NativeSemanticTarget


ARGV = ("/reviewed/python", "-I", "-m", "reviewed.semantic_helper")


class Channel:
    def __init__(self, *args, **kwargs):
        self.construction = args, kwargs
        self.retired = False
        self.requests = []
        self.bootstrap = {"protocol": 1, "semantic": 1}
        self.cleanup_reply = {"cleaned": True}
        self.close_failure = False

    def request(self, operation, payload, *, check, **kwargs):
        check()
        self.requests.append((operation, payload))
        if operation == "configure":
            return {"ready": True}
        return self.bootstrap if operation == "bootstrap" else self.cleanup_reply

    def close(self):
        if self.close_failure:
            raise AgentTaskError("retirement unconfirmed")
        self.retired = True


@pytest.fixture
def routed(monkeypatch, tmp_path):
    local, service = [], []

    def create(destination):
        def construct(*args, **kwargs):
            result = Channel(*args, **kwargs)
            destination.append(result)
            return result
        return construct

    monkeypatch.setattr(factory, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(factory, "load_binding", lambda: factory.OwnerServiceBinding(
        "/run/reviewed.sock", {ARGV: 7}))
    monkeypatch.setattr(native_channel, "OwnedChannel", create(local))
    monkeypatch.setattr(helper_owner_linux, "OwnerServiceChannel", create(service))
    monkeypatch.setattr(helper_owner_linux, "SeqpacketTransport", lambda endpoint: endpoint)
    target = NativeSemanticTarget(argv=ARGV, resource_path=tmp_path / "semantic.lock")
    try:
        yield target, local, service
    finally:
        for channel in local + service:
            channel.cleanup_reply = {"cleaned": True}
            channel.close_failure = False
        target.cleanup()


def test_semantic_proxy_uses_exact_owner_service_policy(routed):
    target, local, service = routed
    checks = []
    def control(_kind):
        return None
    channel = target._launch(lambda: checks.append("checked"), control)
    assert channel is service[0] and not local
    assert channel.construction == (("/run/reviewed.sock", 7, ()), {"on_control": control, "parent": None})
    assert channel.requests == [("bootstrap", {})] and checks == ["checked"]
    target.cleanup()
    assert channel.retired and target._channel is None
    assert channel.requests[-1] == ("cleanup", {"keys": [], "buttons": []})


def test_managed_readiness_cannot_select_display_route_from_task_options(routed):
    target, local, service = routed
    definition = AgentTaskSpec(goal="read fixture", target="fixture", allowed_tools=("AC_increment",),
                               success_criteria=({"kind": "semantic", "tool": "AC_increment",
                                                  "fields": {"value": 1}},),
                               options={"display": True})
    with operation_scope(TaskOperation(definition, lambda: None, None)):
        assert target.ready(definition) == (True, "")
    assert not local and len(service) == 1
    assert [operation for operation, _ in service[0].requests] == ["bootstrap", "configure"]
    assert target._resource is not None and target._journal is not None
    target.cleanup()
    assert target._resource is None and target._journal is None and service[0].retired


@pytest.mark.parametrize("fault", ["missing_policy", "binding_refused", "service_unreachable"])
def test_configured_service_failure_never_falls_back(routed, monkeypatch, fault):
    target, local, service = routed

    def refuse(*_args, **_kwargs):
        raise AgentTaskError("injected service refusal")

    if fault == "missing_policy":
        monkeypatch.setattr(factory, "load_binding", lambda: factory.OwnerServiceBinding("/run/reviewed.sock", {}))
    elif fault == "binding_refused":
        monkeypatch.setattr(factory, "load_binding", refuse)
    else:
        monkeypatch.setattr(helper_owner_linux, "SeqpacketTransport", refuse)
    with pytest.raises(AgentTaskError):
        target._launch(lambda: None)
    assert not local and not service and target._channel is None


def test_lazy_service_connection_failure_retains_original_channel(routed, monkeypatch):
    target, local, service = routed
    original = Channel.request

    def failed_request(self, operation, payload, **kwargs):
        if operation == "bootstrap":
            raise AgentTaskError("injected lazy connection failure")
        return original(self, operation, payload, **kwargs)

    monkeypatch.setattr(Channel, "request", failed_request)
    with pytest.raises(AgentTaskError, match="lazy connection failure"):
        target._launch(lambda: None)
    assert target._channel is service[0] and not local
    target.cleanup()
    assert service[0].retired and len(service) == 1


def test_absent_binding_keeps_documented_local_route(routed, monkeypatch):
    target, local, service = routed
    monkeypatch.setattr(factory, "load_binding", lambda: None)
    channel = target._launch(lambda: None)
    assert channel is local[0] and not service
    assert channel.requests == [("bootstrap", {})]


def test_desktop_proxy_keeps_display_route_with_service_configured(routed, tmp_path):
    _, local, service = routed
    target = NativeDesktopTarget(argv=ARGV, resource_path=tmp_path / "desktop.lock")
    try:
        channel = target._launch(lambda: None)
        assert channel is local[0] and not service
    finally:
        target.cleanup()


@pytest.mark.parametrize("local_route", [False, True])
def test_incompatible_bootstrap_retires_original_channel(routed, monkeypatch, local_route):
    target, local, service = routed
    if local_route:
        monkeypatch.setattr(factory, "load_binding", lambda: None)
    monkeypatch.setattr(target, "_supports_bootstrap", lambda _reply: False)
    with pytest.raises(AgentTaskError, match="bootstrap"):
        target._launch(lambda: None)
    channel = (local if local_route else service)[0]
    assert channel.retired and target._channel is channel


@pytest.mark.parametrize("fault", ["reply", "retirement"])
def test_failed_service_cleanup_retains_owner_until_retry(routed, fault):
    target, local, service = routed
    channel = target._launch(lambda: None)
    if fault == "reply":
        channel.cleanup_reply = {"cleaned": False}
    else:
        channel.close_failure = True
    with pytest.raises(AgentTaskError):
        target.cleanup()
    assert target._channel is channel and not channel.retired
    channel.cleanup_reply = {"cleaned": True}
    channel.close_failure = False
    target.cleanup()
    assert channel.retired and target._channel is None
    assert not local and len(service) == 1
