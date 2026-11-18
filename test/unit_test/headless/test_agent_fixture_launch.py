"""Join owned IPC launch to measured identity using injected calls, never native execution."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.fixture_launch import OwnedChannelLauncher
from je_auto_control.utils.process_memory.models import MemoryObservationError
from headless.test_process_memory_launch import LaunchKernel, attest, pin

CHALLENGE = bytes(range(1, 17))


class Channel:
    def __init__(self):
        self._process = SimpleNamespace(pid=42, _handle=77)
        self.retired = False
        self.closed = 0
        self.fail_close = False
        self.bootstrap = {"kind": "bootstrap", "protocol_version": 1, "schema_version": 1,
                          "identity": "self_reported", "pid": 42, "pointer_bits": 64,
                          "header_address": 4096, "header_size": 40,
                          "payload_address": 8192, "payload_size": 16,
                          "sequence_address": 12288, "sequence_size": 8,
                          "launch_nonce": "1" * 32}

    def request(self, operation, payload, **kwargs):
        assert operation == "bootstrap" and payload == {}
        kwargs["check"]()
        return dict(self.bootstrap)

    def close(self):
        self.closed += 1
        if self.fail_close:
            raise AgentTaskError("retirement pending")
        self.retired = True


def setup():
    kernel, channel = LaunchKernel(), Channel()
    calls = []

    def factory(argv):
        assert kernel.CreateFileW.calls
        calls.append(tuple(argv))
        return channel

    launcher = OwnedChannelLauncher(("--rpc", "--challenge", CHALLENGE.hex()), kernel=kernel,
                                     last_error=lambda: kernel.error, caller_bits=64,
                                     channel_factory=factory)
    return kernel, channel, calls, launcher


def test_attestation_measures_same_owned_channel_then_binds_bootstrap():
    kernel, channel, calls, launcher = setup()
    launch, *_ = attest(kernel, launcher=launcher)
    try:
        assert calls == [(kernel.image_path, "--rpc", "--challenge", CHALLENGE.hex())]
        assert kernel.GetProcessTimes.calls[0][0] == 77
        control = launcher.bind_control(launch, CHALLENGE, checkpoint=lambda: None)
        session = control.bootstrap(timeout=1, checkpoint=lambda: None)
        assert session.binding.pid == launch.identity.pid == 42
        assert launch.identity.birth == kernel.birth
        with pytest.raises(AgentTaskError, match="reused"):
            launcher(kernel.image_path)
    finally:
        launcher.close()
        launch.close()
    assert channel.retired


def test_wrong_pin_prevents_channel_creation():
    kernel, channel, calls, launcher = setup()
    with pytest.raises(MemoryObservationError, match="unsupported"):
        attest(kernel, launcher=launcher, pinned=pin(kernel, sha256="0" * 64))
    assert calls == [] and channel.closed == 0
    launcher.close()


def test_measurement_failure_retains_failed_cleanup_for_retry():
    kernel, channel, _, launcher = setup()
    channel._process.pid = 43
    channel.fail_close = True
    with pytest.raises(MemoryObservationError, match="target_changed"):
        attest(kernel, launcher=launcher)
    assert channel.closed == 1 and not channel.retired
    channel.fail_close = False
    launcher.close()
    assert channel.closed == 2 and channel.retired
    with pytest.raises(AgentTaskError):
        launcher(kernel.image_path)


@pytest.mark.parametrize("changes", [{"pid": 43}, {"pointer_bits": 32}])
def test_descendant_or_wrong_architecture_bootstrap_never_replaces_identity(changes):
    kernel, channel, _, launcher = setup()
    launch, *_ = attest(kernel, launcher=launcher)
    original = launch.identity
    channel.bootstrap.update(changes)
    try:
        with pytest.raises(MemoryObservationError, match="target_changed"):
            launcher.bind_control(launch, CHALLENGE, checkpoint=lambda: None)
        assert channel.retired and launch.identity is original
    finally:
        launcher.close()
        launch.close()


def test_different_birth_is_rejected_before_bootstrap():
    kernel, channel, _, launcher = setup()
    launch, *_ = attest(kernel, launcher=launcher)
    launch.identity = replace(launch.identity, birth=launch.identity.birth + 1)
    try:
        with pytest.raises(MemoryObservationError, match="target_changed"):
            launcher.bind_control(launch, CHALLENGE, checkpoint=lambda: None)
        assert channel.retired
    finally:
        launcher.close()
        launch.close()


def test_close_during_process_creation_retires_newly_returned_channel():
    kernel, channel = LaunchKernel(), Channel()

    def factory(_argv):
        launcher.close()
        return channel

    launcher = OwnedChannelLauncher((), kernel=kernel, last_error=lambda: kernel.error,
                                     caller_bits=64, channel_factory=factory)
    with pytest.raises(MemoryObservationError, match="unsupported"):
        attest(kernel, launcher=launcher)
    assert channel.retired and not kernel.GetProcessTimes.calls


def test_attestation_failure_leaves_launcher_owner_available():
    kernel, channel, _, launcher = setup()
    original = launcher._factory

    def change_image(argv):
        result = original(argv)
        kernel.file_id = b"g" * 16
        return result

    launcher._factory = change_image
    with pytest.raises(MemoryObservationError, match="target_changed"):
        attest(kernel, launcher=launcher)
    assert not channel.retired
    launcher.close()
    assert channel.retired


def test_failed_launcher_close_also_retires_bound_control():
    kernel, channel, _, launcher = setup()
    launch, *_ = attest(kernel, launcher=launcher)
    control = launcher.bind_control(launch, CHALLENGE, checkpoint=lambda: None)
    channel.fail_close = True
    try:
        with pytest.raises(AgentTaskError, match="pending"):
            launcher.close()
        assert not channel.retired
        with pytest.raises(AgentTaskError, match="retired"):
            control.bootstrap(timeout=1, checkpoint=lambda: None)
        channel.fail_close = False
        launcher.close()
        assert channel.retired
    finally:
        channel.fail_close = False
        launcher.close()
        launch.close()
