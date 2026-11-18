"""Assemble retained image/window owners with injected native calls, never a native UI process."""
from dataclasses import replace

import pytest

from je_auto_control.utils.agent_runtime.context import TaskOperation, operation_scope
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.models import AgentTaskSpec
from je_auto_control.utils.agent_runtime.uia_owner import UiaFixtureImage, owned_uia_target
from je_auto_control.utils.exception.control_signals import OperationCancelledError
from je_auto_control.utils.process_memory.models import MemoryObservationError
from headless.test_agent_scoped_uia import Automation, Node
from headless.test_agent_uia_launch import setup as launch_setup
from headless.test_agent_uia_target import spec
from headless.test_process_memory_image import observer
from headless.test_process_memory_launch import pin


def setup(monkeypatch, **changes):
    kernel, api, channel, calls, launcher = launch_setup()
    lease, watch = observer(kernel), observer(kernel)
    image = UiaFixtureImage(pin(kernel, executable="uia-fixture"), kernel.image_path, "fixture", **changes)
    target = owned_uia_target(image, launcher=launcher, lease=lease, observer=watch)
    root = Node().add(Node("1001", value="17"), Node("1002", value="ready"),
        Node("1003", value=""), Node("1004", enabled=False), Node("1005", password=True),
        Node("1006"), Node("1006"))
    root.properties[30020] = 101
    automation = Automation(root)
    monkeypatch.setattr("je_auto_control.utils.agent_runtime.uia_target._native_automation", lambda: automation)
    return target, kernel, api, channel, calls, lease, watch, image, launcher


def managed(check=lambda: None):
    return operation_scope(TaskOperation(AgentTaskSpec.from_dict(spec()), check, None))


def ready(target):
    return target.ready(AgentTaskSpec.from_dict(spec()))


def test_owned_assembly_is_lazy_and_keeps_both_image_leases_until_cleanup(monkeypatch):
    target, kernel, _, channel, calls, lease, watch, *_ = setup(monkeypatch)
    assert not kernel.CreateFileW.calls and not calls
    with pytest.raises(AgentTaskError):
        ready(target)
    assert not kernel.CreateFileW.calls and not calls
    with managed():
        assert ready(target) == (True, "")
        assert ready(target) == (True, "")
        report = target.observe()
        assert report["status"] == "partial"
        partial = report["sources"]["uia"]["partial"]
        assert partial["fields"]["empty"] == "" and partial["fields"]["enabled"] is False
        assert partial["failures"] == {"duplicate": "ambiguous", "password": "protected"}
        assert partial["capture"]["identity_digest"] == target._source._binding.identity.digest
        assert target._source._binding.identity.executable == "uia-fixture"
        assert not kernel.CloseHandle.calls
        assert len(calls) == 1
    target.cleanup()
    assert channel.retired and not lease.pending_cleanup and not watch.pending_cleanup
    with managed(), pytest.raises(AgentTaskError):
        target.observe()


def test_close_before_readiness_prevents_every_acquisition(monkeypatch):
    target, kernel, _, _, calls, *_ = setup(monkeypatch)
    target.cleanup()
    with managed(), pytest.raises(AgentTaskError):
        ready(target)
    assert not calls and not kernel.CreateFileW.calls


@pytest.mark.parametrize("phase", ["pin", "post_image", "bootstrap", "window", "com"])
def test_failed_acquisition_retires_every_preexisting_owner(monkeypatch, phase):
    target, kernel, api, channel, calls, lease, watch, *_ = setup(monkeypatch)
    if phase == "pin":
        kernel.data += b"changed"
    elif phase == "post_image":
        original = watch.observe
        watch.observe = lambda *a, **kw: replace(original(*a, **kw), sha256="0" * 64)
    elif phase == "bootstrap":
        channel.value["pid"] = 43
    elif phase == "window":
        api.pid = 43
    else:
        def unavailable():
            raise AgentTaskError("COM unavailable")
        monkeypatch.setattr("je_auto_control.utils.agent_runtime.uia_target._native_automation", unavailable)
    with managed(), pytest.raises((AgentTaskError, MemoryObservationError)):
        ready(target)
    assert not lease.pending_cleanup and not watch.pending_cleanup
    assert target._source is None
    assert (not calls) if phase == "pin" else channel.retired
    with managed(), pytest.raises(AgentTaskError):
        ready(target)


@pytest.mark.parametrize("phase", ["lease", "process", "bootstrap", "com"])
def test_cleanup_during_acquisition_prevents_late_publication(monkeypatch, phase):
    target, kernel, _, channel, _, lease, watch, _, launcher = setup(monkeypatch)
    if phase == "lease":
        kernel.after_file_read = target.cleanup
    elif phase == "process":
        original = launcher._factory
        def factory(argv):
            result = original(argv)
            target.cleanup()
            return result
        launcher._factory = factory
    elif phase == "bootstrap":
        original = channel.bootstrap
        def bootstrap(*a, **kw):
            result = original(*a, **kw)
            target.cleanup()
            return result
        channel.bootstrap = bootstrap
    else:
        def create():
            target.cleanup()
            return Automation(Node())
        monkeypatch.setattr("je_auto_control.utils.agent_runtime.uia_target._native_automation", create)
    with managed(), pytest.raises((AgentTaskError, MemoryObservationError)):
        ready(target)
    assert target._source is None and not lease.pending_cleanup and not watch.pending_cleanup


def test_failed_cleanup_attempts_both_leases_and_can_retry(monkeypatch):
    target, kernel, _, channel, _, lease, watch, *_ = setup(monkeypatch)
    with managed():
        ready(target)
    channel.fail_close = True
    kernel.failed_closes = {91, 92}
    with pytest.raises(AgentTaskError):
        target.cleanup()
    assert lease.pending_cleanup and watch.pending_cleanup
    assert {(91,), (92,)} <= set(kernel.CloseHandle.calls)
    channel.fail_close = False
    kernel.failed_closes.clear()
    target.cleanup()
    assert channel.retired and not lease.pending_cleanup and not watch.pending_cleanup


def test_cancellation_after_image_read_preserves_signal_and_retires(monkeypatch):
    target, kernel, _, _, calls, lease, watch, *_ = setup(monkeypatch)
    cancelled = False
    def cancel():
        nonlocal cancelled
        cancelled = True
    def check():
        if cancelled:
            raise OperationCancelledError("owned-uia")
    kernel.after_file_read = cancel
    with managed(check), pytest.raises(OperationCancelledError):
        ready(target)
    assert not calls and not lease.pending_cleanup and not watch.pending_cleanup


@pytest.mark.parametrize("changes", [
    {"path": "relative.exe"}, {"path": "C:\\bad\0.exe"}, {"target_id": ""},
    {"max_image_bytes": True}, {"max_image_bytes": 0}, {"max_image_bytes": (64 << 20) + 1},
    {"attestation_timeout": True}, {"attestation_timeout": float("nan")}, {"attestation_timeout": float("inf")},
    {"attestation_timeout": 10**400},
    {"path": '\\\\host\\share\\fixture.exe'}, {"path": "//host/share/fixture.exe"}, {"path": '\\\\.\\pipe\\fixture'},
    {"path": '\\\\?\\C:\\fixture.exe'}, {"path": 'C:\\a\\..\\fixture.exe'},
], ids=["relative", "nul", "target", "bool-bytes", "zero", "large", "bool-time", "nan", "inf", "huge",
        "unc", "unc-slash", "pipe", "device", "parent"])
def test_invalid_image_contract_refuses_without_acquisition(monkeypatch, changes):
    _, kernel, _, _, calls, _, _, image, _ = setup(monkeypatch)
    with pytest.raises(AgentTaskError):
        replace(image, **changes)
    assert not calls and not kernel.CreateFileW.calls


def test_memory_image_label_and_shared_lease_owner_are_refused(monkeypatch):
    _, kernel, _, _, calls, lease, _, image, launcher = setup(monkeypatch)
    with pytest.raises(AgentTaskError):
        replace(image, pin=pin(kernel))
    with pytest.raises(AgentTaskError):
        owned_uia_target(image, launcher=launcher, lease=lease, observer=lease)
    assert not calls


def test_native_factory_constructs_owners_without_starting_or_loading_com(monkeypatch):
    from je_auto_control.utils.agent_runtime import uia_owner
    _, kernel, _, _, calls, lease, watch, image, launcher = setup(monkeypatch)
    windows = object()
    def create(challenge, **options):
        assert len(challenge) == 16 and options == {"windows": windows}
        return launcher
    owners = iter((lease, watch))
    monkeypatch.setattr(uia_owner.sys, "platform", "win32")
    monkeypatch.setattr(uia_owner, "WindowOwnerQuery", lambda: windows)
    monkeypatch.setattr(uia_owner, "OwnedUiaLauncher", create)
    monkeypatch.setattr(uia_owner, "WindowsImageObserver", lambda: next(owners))
    target = uia_owner.native_uia_target(image)
    assert not calls and not kernel.CreateFileW.calls
    with managed():
        ready(target)
    target.cleanup()
    assert len(calls) == 1


def test_cleanup_keeps_cancellation_and_attempts_remaining_owners(monkeypatch):
    target, _, _, channel, _, lease, watch, *_ = setup(monkeypatch)
    visited = []
    signal = OperationCancelledError("cleanup")
    def cancelled():
        visited.append("observer")
        raise signal
    monkeypatch.setattr(watch, "close", cancelled)
    monkeypatch.setattr(lease, "close", lambda: visited.append("lease"))
    with pytest.raises(OperationCancelledError) as caught:
        target.cleanup()
    assert caught.value is signal and visited == ["observer", "lease"]
    assert channel.closed == 0


def test_image_byte_budget_reaches_attestation_before_launch(monkeypatch):
    target, _, _, _, calls, lease, watch, *_ = setup(monkeypatch, max_image_bytes=1)
    with managed(), pytest.raises(MemoryObservationError, match="budget_exceeded"):
        ready(target)
    assert not calls and not lease.pending_cleanup and not watch.pending_cleanup
