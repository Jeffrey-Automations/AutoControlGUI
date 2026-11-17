"""Prepare a pinned native fixture smoke run; execution requires an explicit CLI option."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from functools import partial
import hashlib
import json
from pathlib import Path
import secrets
import sys
import tempfile
from typing import Any, Callable

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime.fixture_commands import FIXTURE_COMMAND
from je_auto_control.utils.agent_runtime.fixture_control import OwnedFixtureControl
from je_auto_control.utils.agent_runtime.fixture_launch import OwnedChannelLauncher
from je_auto_control.utils.agent_runtime.fixture_target import FixtureImage, OwnedFixtureTarget
from je_auto_control.utils.agent_runtime.models import AgentTaskBudget
from je_auto_control.utils.agent_runtime.semantic_target import SemanticSnapshot
from je_auto_control.utils.exception.control_signals import is_run_interruption
from je_auto_control.utils.executor.run_control import ExecutionStopped
from je_auto_control.utils.process_memory.fixture_probe import FixtureBinding
from je_auto_control.utils.process_memory.models import (
    FailureReason, MemoryObservationError, MemoryRegion, ModuleSpan, ProcessHandle, ProcessIdentity,
    ProcessProvider,
)
from je_auto_control.utils.process_memory.pe_image import plan_pinned_image
from je_auto_control.utils.process_memory.windows_launch import OwnedLaunch, PinnedExecutable
from je_auto_control.utils.process_memory.windows import WindowsProcessProvider
from je_auto_control.utils.process_memory.windows_image import WindowsImageObserver

PAGE_LAYOUTS = {"split": (4, True, True, False), "guard": (0x104, True, True, True),
                "noaccess": (1, True, False, False), "decommitted": (0, False, False, False)}


def _metadata(region: MemoryRegion) -> bool:
    values = (region.base, region.size, region.allocation, region.protection,
              region.committed, region.readable, region.guard)
    return tuple(map(type, values)) == (int, int, int, int, bool, bool, bool)


def _properties(region: MemoryRegion) -> tuple[int, bool, bool, bool]:
    return region.protection, region.committed, region.readable, region.guard


def _page_boundary(first: MemoryRegion, second: MemoryRegion, payload: int) -> bool:
    page = first.size
    return (4096 <= page <= 65536 and page & (page - 1) == 0
            and first.base == first.allocation > 0
            and first.base + page == payload + 8 == second.base
            and second.size == page and second.allocation == first.allocation)


@dataclass
class _PageAttempt:
    layout: str
    payload: int = field(repr=False)
    first: MemoryRegion | None = field(default=None, repr=False)
    second: MemoryRegion | None = field(default=None, repr=False)
    first_read: bool = False
    second_read: bool = False
    invalid: bool = False

    def query(self, address: int, region: MemoryRegion) -> None:
        """Retain exact private query evidence; changed mappings invalidate this attempt."""
        if address not in (self.payload, self.payload + 8):
            return
        if not isinstance(region, MemoryRegion):
            self.invalid = True
            return
        name = "first" if address == self.payload else "second"
        previous = getattr(self, name)
        if previous is not None and previous != region:
            self.invalid = True
        setattr(self, name, region)
        if name == "second" and not self.first_read:
            self.invalid = True

    def read(self, address: int, size: int, *, completed: bool) -> None:
        """Record read boundaries without retaining any payload bytes."""
        if address < self.payload + 16 and address + size > self.payload + 8:
            self.second_read = True
        if address == self.payload and size == 8 and completed:
            if self.first is None:
                self.invalid = True
            self.first_read = True

    def matches(self) -> bool:
        """Require both exact regions on this handle, in the expected read order."""
        first, second = self.first, self.second
        if self.invalid or first is None or second is None or not self.first_read:
            return False
        return (_metadata(first) and _metadata(second)
                and _page_boundary(first, second, self.payload)
                and _properties(first) == (2, True, True, False)
                and _properties(second) == PAGE_LAYOUTS[self.layout]
                and self.second_read == (self.layout == "split"))


class PageTrace:
    """One private bootstrap binding and one read attempt; never combine handles."""

    def __init__(self, layout: str) -> None:
        if layout not in PAGE_LAYOUTS:
            raise ValueError("unsupported page layout")
        self.layout = layout
        self._binding: FixtureBinding | None = None
        self._attempt: _PageAttempt | None = None
        self._opens = 0
        self._claimed = False
        self._consumed = False

    def bind(self, binding: FixtureBinding) -> None:
        """Take only the launcher's already validated bootstrap binding."""
        if self._binding is not None or binding.pointer_bits != 64:
            raise ValueError("page evidence requires one bootstrap binding")
        self._binding = binding

    def opened(self) -> _PageAttempt:
        """Start isolated evidence before the provider acquires its next handle."""
        if self._binding is None or not self._claimed or self._consumed:
            raise ValueError("page evidence has no validated bootstrap")
        self._opens += 1
        self._attempt = _PageAttempt(self.layout, self._binding.payload)
        return self._attempt

    def matches(self) -> bool:
        """Refuse aggregate evidence from multiple observations or handle acquisitions."""
        return (not self._consumed and self._claimed and self._opens == 1
                and self._attempt is not None and self._attempt.matches())

    def begin(self) -> None:
        """Claim a fresh observation before any evidence-producing handle is opened."""
        if self._binding is None or self._claimed or self._opens:
            raise ValueError("page evidence is not fresh")
        self._claimed = True

    def consume(self) -> bool:
        """Use the evidence once; a later observation cannot replay it."""
        matched = self.matches()
        self._consumed = True
        return matched


class _PageHandle:
    def __init__(self, handle: ProcessHandle, attempt: _PageAttempt) -> None:
        self._handle, self._attempt = handle, attempt

    def identity(self) -> ProcessIdentity:
        """Delegate identity measurement to the same retained handle."""
        return self._handle.identity()

    def main_module(self) -> ModuleSpan:
        """Keep module lookup on the underlying measured handle."""
        return self._handle.main_module()

    def query_region(self, address: int) -> MemoryRegion:
        """Observe only queries the reader already requested, without adding calls."""
        region = self._handle.query_region(address)
        self._attempt.query(address, region)
        return region

    def read(self, address: int, size: int) -> bytes:
        """Pass through data unchanged, retaining only successful prefix-read evidence."""
        self._attempt.read(address, size, completed=False)
        value = self._handle.read(address, size)
        self._attempt.read(address, size, completed=isinstance(value, bytes) and len(value) == size)
        return value

    def close(self) -> None:
        """Leave failed-close ownership with the reader's existing handle wrapper."""
        self._handle.close()


# pylint: disable-next=too-few-public-methods  # reason: implements the single-method ProcessProvider contract
class _PageProvider:
    def __init__(self, provider: ProcessProvider, trace: PageTrace) -> None:
        self._provider, self._trace = provider, trace

    def open_readonly(self, identity: ProcessIdentity) -> ProcessHandle:
        """Acquire once and attach one private attempt to that retained handle."""
        attempt = self._trace.opened()
        return _PageHandle(self._provider.open_readonly(identity), attempt)


class _PageLauncher(OwnedChannelLauncher):
    def __init__(self, image: FixtureImage, trace: PageTrace, **options: Any) -> None:
        super().__init__(("--rpc", "--challenge", image.challenge.hex(),
                          "--page-layout", trace.layout), **options)
        self._trace = trace

    def bind_control(self, launch: OwnedLaunch, challenge: bytes, *,
                     checkpoint: Callable[[], None]) -> OwnedFixtureControl:
        """Bind the diagnostic address only after the parent verifies launch identity."""
        control = super().bind_control(launch, challenge, checkpoint=checkpoint)
        self._trace.bind(control.bootstrap(timeout=1, checkpoint=checkpoint).binding)
        return control


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


def native_target(image: FixtureImage, *, trace: PageTrace | None = None) -> OwnedFixtureTarget:
    """Construct native owners only on the explicit Windows execution path."""
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise ValueError("native smoke requires 64-bit Windows")
    launcher = (OwnedChannelLauncher(("--rpc", "--challenge", image.challenge.hex()))
                if trace is None else _PageLauncher(image, trace))

    def provider(attestor):
        actual = WindowsProcessProvider(attestor)
        return actual if trace is None else _PageProvider(actual, trace)

    return OwnedFixtureTarget(image, launcher=launcher, lease=WindowsImageObserver(),
                              observer=WindowsImageObserver(),
                              provider_factory=provider)


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


def _page_read(runtime: AgentRuntime, checks: dict[str, bool], trace: PageTrace) -> None:
    task = runtime.submit(AgentTaskSpec(
        goal="inspect owned fixture page layout", target="fixture",
        allowed_tools=(FIXTURE_COMMAND,),
        success_criteria=({"kind": "semantic", "tool": FIXTURE_COMMAND,
                           "fields": {"job_status": "ready"}},))).task_id
    trace.begin()
    try:
        snapshot = SemanticSnapshot.from_dict(runtime.observe(task).data)
    except MemoryObservationError as error:
        _require(trace.layout != "split" and error.reason is FailureReason.UNREADABLE_REGION
                 and trace.consume())
        checks["expected_reader_refusal"] = True
    else:
        _require(trace.layout == "split" and trace.consume()
                 and dict(snapshot.fields) == {"document_id": 17, "job_status": "ready"}
                 and snapshot.revision == 0)
        checks["split_readback"] = True
    checks["payload_page_evidence"] = True


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
              Callable[[FixtureImage], OwnedFixtureTarget] = native_target,
              page_trace: PageTrace | None = None) -> dict[str, Any]:
    """Run a normal roundtrip or one read-only page case, without command retries."""
    result = report(prepared)
    result["page_layout"] = None if page_trace is None else page_trace.layout
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
        if page_trace is None:
            _roundtrip(runtime, result["checks"])
        else:
            _page_read(runtime, result["checks"], page_trace)
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
    parser.add_argument("--page-layout", choices=tuple(PAGE_LAYOUTS),
                        help="read-only page case; default execution runs the normal roundtrip")
    args = parser.parse_args(argv)
    try:
        prepared = prepare(args.build, args.sha256)
        trace = PageTrace(args.page_layout) if args.page_layout else None
        if args.execute and trace is not None:
            result = run_smoke(prepared, target_factory=partial(native_target, trace=trace),
                               page_trace=trace)
        else:
            result = run_smoke(prepared) if args.execute else report(prepared)
        result["page_layout"] = args.page_layout
    except (ValueError, OSError, MemoryObservationError):
        result = {"schema": 1, "execution": "not_run", "failure": "preparation_failed"}
    print(json.dumps(result, sort_keys=True))
    return int(result.get("failure") is not None)


if __name__ == "__main__":
    raise SystemExit(main())
