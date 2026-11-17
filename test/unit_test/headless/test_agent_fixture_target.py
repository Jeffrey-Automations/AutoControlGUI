"""Exercise complete fixture ownership using injected launch calls and mapped buffers."""
from dataclasses import replace
import struct
import threading

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.fixture_commands import FIXTURE_COMMAND
from je_auto_control.utils.agent_runtime.fixture_target import FixtureImage, OwnedFixtureTarget
from je_auto_control.utils.process_memory.models import MemoryObservationError, ProcessIdentity
from je_auto_control.utils.exception.control_signals import OperationCancelledError
from headless.test_agent_fixture_launch import CHALLENGE, setup as launch_setup
from headless.test_process_memory_image import observer
from headless.test_process_memory_launch import pin
from headless.test_process_memory_pe_image import BASE, Provider, baseline


def setup():
    kernel, channel, calls, launcher = launch_setup()
    kernel.data = bytes(baseline())
    provider = Provider(kernel.data)
    provider.identity = lambda: ProcessIdentity(
        "owned-host", "owned-session", 42, kernel.birth, "fixture", "1", "x64", 64)
    header, payload, sequence = BASE + 0x2200, BASE + 0x2300, BASE + 0x2400
    channel.bootstrap.update(header_address=header, payload_address=payload,
                             sequence_address=sequence)
    struct.pack_into("<8s16sQQ", provider.memory, 0x2200, b"JEPMFIX1", CHALLENGE, payload, sequence)
    struct.pack_into("<I12s", provider.memory, 0x2300, 7, b"ready")
    struct.pack_into("<Q", provider.memory, 0x2400, 0)
    original = channel.request

    def request(operation, value, **kwargs):
        if operation == "bootstrap":
            return original(operation, value, **kwargs)
        kwargs["check"]()
        assert value["expected_sequence"] == struct.unpack_from("<Q", provider.memory, 0x2400)[0]
        revision = value["expected_sequence"] + 2
        struct.pack_into("<I12s", provider.memory, 0x2300,
                         value["document_id"], value["job_status"].encode())
        struct.pack_into("<Q", provider.memory, 0x2400, revision)
        return {"kind": "receipt", "comparison": "atomic", "sequence": revision,
                **{key: value[key] for key in ("operation_id", "launch_nonce", "document_id", "job_status")}}

    channel.request = request
    lease, watch = observer(kernel), observer(kernel)
    image = FixtureImage(pin(kernel), kernel.image_path, kernel.data, CHALLENGE, "fixture", read_timeout=5)
    target = OwnedFixtureTarget(image, launcher=launcher, lease=lease, observer=watch,
                                provider_factory=lambda _: provider)
    return target, kernel, channel, calls, provider, lease, watch


def test_runtime_reads_acts_verifies_and_retires_every_owner(tmp_path):
    target, kernel, channel, calls, provider, lease, watch = setup()
    assert target.start(checkpoint=lambda: None) is target
    spec = AgentTaskSpec(goal="finish fixture", target="fixture", allowed_tools=(FIXTURE_COMMAND,),
                         success_criteria=({"kind": "semantic", "tool": FIXTURE_COMMAND,
                                            "fields": {"document_id": 42, "job_status": "done"}},))
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target})
    try:
        task = runtime.submit(spec).task_id
        frame = runtime.observe(task)
        runtime.act(task, {"tool": FIXTURE_COMMAND, "observation_id": frame.observation_id,
                          "arguments": {"document_id": 42, "job_status": "done"}})
        assert runtime.finish(task).state == "succeeded"
        assert channel.retired and not lease.pending_cleanup and not watch.pending_cleanup
    finally:
        runtime.close()
        target.cleanup()
    assert len(calls) == 1 and provider.closed > 0 and channel.retired
    assert not lease.pending_cleanup and not watch.pending_cleanup
    assert kernel.CloseHandle.calls
    with pytest.raises(AgentTaskError, match="retired"):
        target.observe()


@pytest.mark.parametrize("change", ["pin", "challenge", "version"])
def test_invalid_host_configuration_never_launches(change):
    target, _, _, calls, *_ = setup()
    image = target._image
    if change == "pin":
        image = replace(image, pin=replace(image.pin, sha256="0" * 64))
    elif change == "version":
        image = replace(image, pin=replace(image.pin, version="2"))
    else:
        image = replace(image, challenge=b"\0" * 16)
    target._image = image
    with pytest.raises(MemoryObservationError):
        target.start(checkpoint=lambda: None)
    assert not calls
    with pytest.raises(AgentTaskError, match="retired"):
        target.start(checkpoint=lambda: None)


def test_cleanup_failure_retains_all_owners_and_stops_use():
    target, kernel, channel, _, _, lease, watch = setup()
    target.start(checkpoint=lambda: None)
    channel.fail_close = True
    kernel.failed_closes = {91, 92}
    with pytest.raises(AgentTaskError):
        target.cleanup()
    assert lease.pending_cleanup and watch.pending_cleanup
    with pytest.raises(AgentTaskError, match="retired"):
        target.observe()
    channel.fail_close = False
    kernel.failed_closes.clear()
    target.cleanup()
    assert channel.retired and not lease.pending_cleanup and not watch.pending_cleanup


@pytest.mark.parametrize("phase", ["bootstrap", "provider"])
def test_cleanup_during_startup_prevents_late_publication(phase):
    target, _, channel, _, provider, lease, watch = setup()
    if phase == "bootstrap":
        original = channel.request

        def interrupt(*args, **kwargs):
            target.cleanup()
            return original(*args, **kwargs)

        channel.request = interrupt
    else:
        def factory(_):
            target.cleanup()
            return provider

        target._provider_factory = factory
    with pytest.raises(AgentTaskError, match="retired"):
        target.start(checkpoint=lambda: None)
    assert target._target is None and channel.retired
    assert not lease.pending_cleanup and not watch.pending_cleanup


def test_successful_start_cannot_be_repeated():
    target, _, _, calls, *_ = setup()
    target.start(checkpoint=lambda: None)
    try:
        with pytest.raises(AgentTaskError, match="twice"):
            target.start(checkpoint=lambda: None)
        assert len(calls) == 1
    finally:
        target.cleanup()


def test_startup_failure_keeps_failed_cleanup_available():
    target, kernel, channel, _, _, lease, watch = setup()
    channel.bootstrap["pid"] = 43
    channel.fail_close = True
    kernel.failed_closes = {91, 92}
    with pytest.raises(MemoryObservationError, match="target_changed"):
        target.start(checkpoint=lambda: None)
    assert lease.pending_cleanup and watch.pending_cleanup
    channel.fail_close = False
    kernel.failed_closes.clear()
    target.cleanup()
    assert channel.retired and not lease.pending_cleanup and not watch.pending_cleanup


def test_cancellation_after_launch_retires_without_publishing():
    target, _, channel, calls, _, lease, watch = setup()
    signal = OperationCancelledError("stop")

    def check():
        if calls:
            raise signal

    with pytest.raises(OperationCancelledError) as caught:
        target.start(checkpoint=check)
    assert caught.value is signal and target._target is None
    assert channel.retired and not lease.pending_cleanup and not watch.pending_cleanup


def test_changed_code_never_publishes_semantic_fields(tmp_path):
    target, _, _, _, provider, *_ = setup()
    target.start(checkpoint=lambda: None)
    provider.memory[0x1000] ^= 1
    runtime = AgentRuntime(tmp_path / "runtime.sqlite", targets={"fixture": target})
    try:
        task = runtime.submit(AgentTaskSpec(goal="read", target="fixture",
                                            allowed_tools=(FIXTURE_COMMAND,),
                                            success_criteria=({"kind": "semantic", "tool": FIXTURE_COMMAND,
                                                               "fields": {"job_status": "done"}},))).task_id
        with pytest.raises(MemoryObservationError, match="unsupported"):
            runtime.observe(task)
        assert all(address < BASE + 0x2200 for address, _ in provider.reads)
    finally:
        runtime.close()
        target.cleanup()


@pytest.mark.parametrize("timeout", [0, 61, float("nan"), True])
def test_invalid_read_deadline_refused_before_launch(timeout):
    target, _, _, calls, *_ = setup()
    target._image = replace(target._image, read_timeout=timeout)
    with pytest.raises(MemoryObservationError):
        target.start(checkpoint=lambda: None)
    assert not calls


@pytest.mark.parametrize("signal", [KeyboardInterrupt(), OperationCancelledError("stop")])
def test_cleanup_preserves_interruption_after_ordinary_failure(signal):
    target, _, channel, _, _, lease, watch = setup()
    target.start(checkpoint=lambda: None)
    channel.fail_close = True
    original = watch.close

    def interrupted():
        original()
        raise signal

    watch.close = interrupted
    with pytest.raises(type(signal)) as caught:
        target.cleanup()
    assert caught.value is signal and not lease.pending_cleanup
    watch.close = original
    channel.fail_close = False
    target.cleanup()


def test_concurrent_cleanup_does_not_wait_for_startup_or_publish_late_target():
    target, _, channel, _, provider, lease, watch = setup()
    entered, release = threading.Event(), threading.Event()
    errors = []

    def factory(_):
        entered.set()
        assert release.wait(5)
        return provider

    def start():
        try:
            target.start(checkpoint=lambda: None)
        except AgentTaskError as error:
            errors.append(error)

    target._provider_factory = factory
    worker = threading.Thread(target=start)
    worker.start()
    try:
        assert entered.wait(5)
        target.cleanup()
        assert worker.is_alive() and channel.retired
        assert not lease.pending_cleanup and not watch.pending_cleanup
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and len(errors) == 1
    assert target._target is None
