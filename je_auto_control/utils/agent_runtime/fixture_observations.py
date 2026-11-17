"""Corroborate reviewed fixture memory with its retained launch-bound read-only IPC source."""
from __future__ import annotations

import time
from typing import Callable
from uuid import uuid4

from .errors import AgentTaskError
from .fixture_commands import FixtureControl
from .fixture_control import _validate_reply
from .memory_target import MemoryBinding, MemorySemanticTarget
from .observation_report import ObservationReport
from .semantic_snapshot import SemanticSnapshot
from ..process_memory.models import FailureReason, MemoryObservationError

FIXTURE_SOURCES = ("process_memory", "fixture_protocol")
_MISSING = frozenset({FailureReason.ACCESS_DENIED, FailureReason.UNREADABLE_REGION,
                      FailureReason.PARTIAL_READ, FailureReason.INCONSISTENT_SNAPSHOT,
                      FailureReason.DEADLINE_EXCEEDED, FailureReason.BUDGET_EXCEEDED, FailureReason.DECODE_FAILED})


class FixtureObservations:
    """Use the measured binding for both sources; payloads cannot provide identity or source metadata."""

    def __init__(self, binding: MemoryBinding, memory: MemorySemanticTarget, control: FixtureControl) -> None:
        self._binding, self._memory, self._control = binding, memory, control

    def observe(self, checkpoint: Callable[[], None]) -> ObservationReport:
        """Retain safe memory failures, but propagate scope, lifetime, transport and cleanup errors."""
        started = time.monotonic()
        checkpoint()
        try:
            memory: SemanticSnapshot | str = SemanticSnapshot.from_dict(self._memory.observe())
        except MemoryObservationError as error:
            if error.reason not in _MISSING:
                raise
            memory = error.reason.value
        checkpoint()
        protocol = self._snapshot(checkpoint)
        checkpoint()
        return ObservationReport(FIXTURE_SOURCES[0], ((FIXTURE_SOURCES[0], memory),
                                 (FIXTURE_SOURCES[1], protocol)), started, time.monotonic())

    def _snapshot(self, checkpoint: Callable[[], None]) -> SemanticSnapshot:
        started = time.monotonic()
        reply = self._control.request({"command": "snapshot"}, timeout=1.0, checkpoint=checkpoint)
        checkpoint()
        value = _validate_reply(dict(reply), "snapshot")
        if value["kind"] != "snapshot":
            raise AgentTaskError("fixture snapshot was refused")
        binding = self._binding
        return SemanticSnapshot(target_id=binding.target_id, identity_digest=binding.identity.digest,
            adapter_id="fixture-ipc", schema_version="1", source=FIXTURE_SOURCES[1],
            fields=(("document_id", value["document_id"]), ("job_status", value["job_status"])),
            revision=value["sequence"], consistency="sequence_checked", observation_id=uuid4().hex,
            started=started, finished=time.monotonic())
