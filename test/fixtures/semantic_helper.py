"""Run a repository-owned semantic IPC target without any desktop or memory access."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from je_auto_control.utils.agent_runtime.errors import AgentEffectUnknown, AgentObservationStale
from je_auto_control.utils.agent_runtime.native_worker import NativeWorker
from je_auto_control.utils.agent_runtime.semantic_target import SemanticReceipt, SemanticSnapshot, SemanticTarget
from je_auto_control.utils.process_memory.models import FailureReason, MemoryObservationError


def mark_entered(marker: Path) -> None:
    """Publish the marker whole: a reader polling for the file never sees it empty."""
    staged = marker.with_name(marker.name + ".tmp")
    staged.write_text("entered", encoding="utf-8")
    os.replace(staged, marker)


class FixtureTarget(SemanticTarget):
    """Only this helper changes its counter; no application or desktop resources are opened."""

    def __init__(self):
        self.worker = None
        self.started_marker = None
        self.state = SemanticSnapshot(target_id="fixture", identity_digest=hashlib.sha256(uuid4().bytes).hexdigest(),
            adapter_id="fixture-ipc", schema_version="1", source="fixture_protocol",
            fields=(("value", 0),), revision=0, consistency="sequence_checked",
            observation_id="initial", started=0, finished=0)

    def ready(self, _spec):
        return True, ""

    def observe(self):
        now = time.perf_counter()
        return replace(self.state, observation_id=uuid4().hex, started=now, finished=now).to_dict()

    def perform_grounded(self, name, arguments, *, expected, operation_id):
        if arguments.get("memory_failure"):
            raise MemoryObservationError(FailureReason(arguments["memory_failure"]))
        if expected.grounding() != self.state.grounding():
            raise AgentObservationStale("fixture changed before commit")
        if arguments.get("input"):
            self.worker._input({"kind": "key_press", "keycode": 65, "is_shift": False})
        if arguments.get("hang"):
            if self.started_marker is not None:
                mark_entered(self.started_marker)
            threading.Event().wait(30)
        if not arguments.get("no_effect"):
            self.state = replace(self.state, fields=(("value", 1),), revision=self.state.revision + 2)
        if arguments.get("lose_reply"):
            raise AgentEffectUnknown("fixture reply lost; readback required")
        return SemanticReceipt(operation_id, "atomic", {"value": 1})

    def cleanup(self):
        pass


if __name__ == "__main__":
    target = FixtureTarget()
    if len(sys.argv) == 2:
        target.started_marker = Path(sys.argv[1])
    target.worker = NativeWorker(sys.stdin.buffer, sys.stdout.buffer, target=target)
    target.worker.run()
