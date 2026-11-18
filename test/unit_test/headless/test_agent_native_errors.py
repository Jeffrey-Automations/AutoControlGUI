"""Preserve closed memory failure codes across IPC without publishing exception details."""
from io import BytesIO
import json

import pytest

from je_auto_control.utils.agent_runtime.errors import AgentTaskError, AgentEffectUnknown
from je_auto_control.utils.agent_runtime.native_channel import classify_reply
from je_auto_control.utils.agent_runtime.native_errors import error_reply
from je_auto_control.utils.agent_runtime.native_worker import NativeWorker
from je_auto_control.utils.process_memory.models import FailureReason, MemoryObservationError


class PrivateFailure(MemoryObservationError):
    def __str__(self):
        raise AssertionError("memory exception text must never be serialized")


@pytest.mark.parametrize("reason", list(FailureReason))
def test_every_reason_survives_without_exception_text(reason):
    packet = error_reply("request-1", PrivateFailure(reason))
    assert packet == {"id": "request-1", "error_type": "MemoryObservationError",
                      "error": "memory observation failed", "memory_reason": reason.value}
    with pytest.raises(MemoryObservationError) as failure:
        classify_reply(packet, "request-1")
    assert failure.value.reason is reason
    assert str(failure.value) == reason.value


@pytest.mark.parametrize("changes", [
    {"memory_reason": "PRIVATE unknown reason"}, {"memory_reason": []},
    {"error": "PRIVATE bytes at 0xfeed"}, {"error_type": "Other"},
    {"result": "PRIVATE bytes"}, {"event": {"kind": "mouse_press"}},
])
def test_malformed_memory_reply_refuses_without_echo_or_event(changes):
    packet = error_reply("request-1", MemoryObservationError(FailureReason.PARTIAL_READ)) | changes
    with pytest.raises(AgentTaskError) as failure:
        classify_reply(packet, "request-1")
    assert str(failure.value) == "native helper returned an invalid memory failure"


@pytest.mark.parametrize("missing", ["error", "memory_reason", "error_type"])
def test_incomplete_memory_failure_is_never_a_result(missing):
    packet = error_reply("request-1", MemoryObservationError(FailureReason.PARTIAL_READ))
    del packet[missing]
    with pytest.raises(AgentTaskError):
        classify_reply(packet, "request-1")


def test_mutated_exception_reason_is_sanitized_before_encoding():
    failure = PrivateFailure(FailureReason.PARTIAL_READ)
    failure.reason = "PRIVATE bytes"
    packet = error_reply("request-1", failure)
    assert packet["error"] == "invalid memory failure"
    assert "PRIVATE" not in json.dumps(packet)


def test_existing_effect_unknown_type_is_preserved():
    with pytest.raises(AgentEffectUnknown, match="readback required"):
        classify_reply(error_reply("request-1", AgentEffectUnknown("readback required")), "request-1")


def test_worker_encodes_memory_failure_from_real_dispatch_boundary():
    source = BytesIO(b'{"id":"request-1","operation":"observe","payload":{}}\n')
    sink = BytesIO()
    worker = NativeWorker(source, sink, target=object())

    def fail(_operation, _payload):
        raise PrivateFailure(FailureReason.ACCESS_DENIED)

    worker._dispatch = fail
    worker._serve()
    reply = json.loads(sink.getvalue())
    with pytest.raises(MemoryObservationError) as failure:
        classify_reply(reply, "request-1")
    assert failure.value.reason is FailureReason.ACCESS_DENIED
