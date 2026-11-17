"""Prepare a pinned native fixture smoke run; execution requires an explicit CLI option."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import secrets
import sys
import tempfile
from typing import Any, Callable

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime.fixture_commands import FIXTURE_COMMAND
from je_auto_control.utils.agent_runtime.fixture_launch import OwnedChannelLauncher
from je_auto_control.utils.agent_runtime.fixture_target import FixtureImage, OwnedFixtureTarget
from je_auto_control.utils.agent_runtime.models import AgentTaskBudget
from je_auto_control.utils.agent_runtime.semantic_target import SemanticSnapshot
from je_auto_control.utils.exception.control_signals import is_run_interruption
from je_auto_control.utils.executor.run_control import ExecutionStopped
from je_auto_control.utils.process_memory.models import MemoryObservationError
from je_auto_control.utils.process_memory.pe_image import plan_pinned_image
from je_auto_control.utils.process_memory.windows_launch import PinnedExecutable
from je_auto_control.utils.process_memory.windows import WindowsProcessProvider
from je_auto_control.utils.process_memory.windows_image import WindowsImageObserver


@dataclass(frozen=True)
class PreparedFixture:
    """Static inventory match, not a source-to-binary certificate or native acceptance."""

    image: FixtureImage = field(repr=False)
    checked_bytes: int
    source_sha256: str


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("artifact exceeds limit")
    return value


def prepare(build: Path, expected_sha256: str) -> PreparedFixture:
    """Check bounded build artifacts against the independently supplied image pin."""
    build = build.resolve()
    try:
        manifest = json.loads(_read(build / "manifest.json", 16384))
    except (ValueError, RecursionError):
        raise ValueError("invalid build inventory") from None
    required = {"schema": 1, "architecture": "x64", "crt": "static",
                "imported_dlls": ["bcrypt.dll", "kernel32.dll"]}
    if not isinstance(manifest, dict) or any(
            type(manifest.get(key)) is not type(value) or manifest[key] != value
            for key, value in required.items()):
        raise ValueError("unsupported build inventory")
    source = _read(build / "fixture.c", 1 << 20)
    source_hash = hashlib.sha256(source).hexdigest()
    if (source != _read(Path(__file__).with_name("fixture.c"), 1 << 20)
            or manifest.get("source_sha256") != source_hash
            or manifest.get("image_sha256") != expected_sha256):
        raise ValueError("build inventory mismatch")
    image_path = build / "memory_fixture.exe"
    raw = _read(image_path, 64 << 20)
    pin = PinnedExecutable("acceptance-host", secrets.token_hex(16),
                           "fixture", "1", expected_sha256)
    plan = plan_pinned_image(raw, pin)
    image = FixtureImage(pin, str(image_path), raw, secrets.token_bytes(16),
                         "fixture", read_timeout=60)
    return PreparedFixture(image, plan.checked_bytes, source_hash)


def report(prepared: PreparedFixture) -> dict[str, Any]:
    """Keep runtime, dependency and desktop evidence separate."""
    return {"schema": 1, "image_sha256": prepared.image.pin.sha256,
            "source_sha256": prepared.source_sha256, "checked_bytes": prepared.checked_bytes,
            "read_budget_seconds": prepared.image.read_timeout,
            "execution": "not_run", "checks": {}, "cleanup_attempts": 0,
            "cleanup_confirmed": False, "failure": None,
            "dependency_trust": "not_verified", "foreground_noninterference": "not_verified",
            "fault_matrix": "not_verified", "full_native_acceptance": "not_verified"}


def native_target(image: FixtureImage) -> OwnedFixtureTarget:
    """Construct native owners only on the explicit Windows execution path."""
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise ValueError("native smoke requires 64-bit Windows")
    launcher = OwnedChannelLauncher(("--rpc", "--challenge", image.challenge.hex()))
    return OwnedFixtureTarget(image, launcher=launcher, lease=WindowsImageObserver(),
                              observer=WindowsImageObserver(),
                              provider_factory=WindowsProcessProvider)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("smoke evidence mismatch")


def _roundtrip(runtime: AgentRuntime, checks: dict[str, bool]) -> None:
    expected = {"document_id": 42, "job_status": "done"}
    task = runtime.submit(AgentTaskSpec(
        goal="verify owned fixture roundtrip", target="fixture", allowed_tools=(FIXTURE_COMMAND,),
        budget=AgentTaskBudget(action_seconds=60),
        success_criteria=({"kind": "semantic", "tool": FIXTURE_COMMAND,
                           "fields": expected},))).task_id
    initial = runtime.observe(task)
    snapshot = SemanticSnapshot.from_dict(initial.data)
    _require(dict(snapshot.fields) == {"document_id": 17, "job_status": "ready"}
             and snapshot.revision == 0)
    checks["initial_state"] = True
    receipt = runtime.act(task, {"tool": FIXTURE_COMMAND, "observation_id": initial.observation_id,
                                 "arguments": expected})
    _require(receipt.status == "confirmed" and receipt.result["comparison"] == "atomic")
    checks["operation_receipt"] = True
    after = SemanticSnapshot.from_dict(runtime.observe(task).data)
    _require(dict(after.fields) == expected and after.revision == 2
             and after.identity_digest == snapshot.identity_digest)
    checks["independent_readback"] = True
    _require(runtime.finish(task).state == "succeeded")
    checks["runtime_completion"] = True


def _cleanup(owners: list[Any], result: dict[str, Any]) -> list[BaseException]:
    errors: list[BaseException] = []
    for attempt in range(1, 3):
        failed = []
        for owner, method in owners:
            try:
                getattr(owner, method)()
            # pylint: disable-next=broad-exception-caught  # reason: record every cleanup and preserve signals after retirement attempts
            except BaseException as error:
                errors.append(error)
                failed.append((owner, method))
        result["cleanup_attempts"] = attempt
        owners = failed
        if not owners:
            result["cleanup_confirmed"] = True
            break
    return errors


def _failure(errors: list[BaseException]) -> str | None:
    for error in errors:
        if (not isinstance(error, Exception) or isinstance(error, ExecutionStopped)
                or is_run_interruption(error)):
            raise error
    if not errors:
        return None
    error = errors[0]
    return error.reason.value if isinstance(error, MemoryObservationError) else "smoke_failed"


def run_smoke(prepared: PreparedFixture, *, target_factory:
              Callable[[FixtureImage], OwnedFixtureTarget] = native_target) -> dict[str, Any]:
    """Run one command with fresh readback; never retry commands after unknown effects."""
    result = report(prepared)
    owners: list[Any] = []
    errors: list[BaseException] = []
    try:
        # pylint: disable-next=consider-using-with  # reason: aggregate directory and native-owner cleanup failures
        directory = tempfile.TemporaryDirectory(prefix="fixture-acceptance-")
        owners.append((directory, "cleanup"))
        target = target_factory(prepared.image)
        owners.insert(0, (target, "cleanup"))
        target.start(checkpoint=lambda: None)
        runtime = AgentRuntime(Path(directory.name) / "runtime.sqlite", targets={"fixture": target})
        owners.insert(0, (runtime, "close"))
        _roundtrip(runtime, result["checks"])
    # pylint: disable-next=broad-exception-caught  # reason: always retire owners before preserving interruption
    except BaseException as error:
        errors.append(error)
    finally:
        errors.extend(_cleanup(owners, result))
    result["failure"] = _failure(errors)
    result["execution"] = "passed" if not errors and result["cleanup_confirmed"] else "failed"
    return result


def main(argv: list[str] | None = None) -> int:
    """Print a bounded JSON report; default mode only reads static files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--sha256", required=True, help="independently reviewed executable hash")
    parser.add_argument("--execute", action="store_true",
                        help="run only after native acceptance is resumed")
    args = parser.parse_args(argv)
    try:
        prepared = prepare(args.build, args.sha256)
        result = run_smoke(prepared) if args.execute else report(prepared)
    except (ValueError, OSError, MemoryObservationError):
        result = {"schema": 1, "execution": "not_run", "failure": "preparation_failed"}
    print(json.dumps(result, sort_keys=True))
    return int(result.get("failure") is not None)


if __name__ == "__main__":
    raise SystemExit(main())
