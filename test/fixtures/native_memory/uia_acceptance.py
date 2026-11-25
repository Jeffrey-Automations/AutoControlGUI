"""Read the owned hidden UI fixture through the managed runtime; execution needs an explicit option.

Nothing is clicked, typed, focused or shown. While it runs, a sampler records whether the
foreground window ever belonged to the fixture; other programs may change it, which says nothing
about the fixture.
"""
from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from typing import Any

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime.uia_owner import UiaFixtureImage, native_uia_target
from je_auto_control.utils.process_memory.windows_launch import PinnedExecutable
from je_auto_control.utils.process_memory.windows_window import WindowOwnerQuery

EXPECTED = {"document_id": "17", "job_status": "ready", "empty": "", "enabled": False}
REFUSED = {"duplicate": "ambiguous", "password": "protected"}


class Foreground:
    """Sample which process owns the foreground window; read-only."""

    def __init__(self) -> None:
        self._user = ctypes.WinDLL("user32")
        self._user.GetForegroundWindow.restype = ctypes.c_void_p
        self._query, self._stop = WindowOwnerQuery(), threading.Event()
        self.owners: set[int] = set()
        self.samples = 0
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(0.005):
            window = self._user.GetForegroundWindow()
            if window:
                try:
                    self.owners.add(self._query.process_id(window))
                except Exception:  # reason: the window closed between the two reads
                    continue
                self.samples += 1

    def __enter__(self) -> Foreground:
        self._thread.start()
        return self

    def __exit__(self, *_error: object) -> None:
        self._stop.set()
        self._thread.join(5)


def observe_twice(target: Any, checks: dict[str, bool]) -> None:
    """Two captures of one managed task must agree on identity and publish only readable fields."""
    with tempfile.TemporaryDirectory(prefix="uia-acceptance-") as directory:
        runtime = AgentRuntime(Path(directory) / "runtime.sqlite", targets={"uia-fixture": target})
        try:
            task = runtime.submit(AgentTaskSpec(
                goal="read the owned UI fixture", target="uia-fixture", allowed_tools=("AC_screenshot",),
                success_criteria=({"kind": "actions_complete"},))).task_id
            partials = [runtime.observe(task).data["sources"]["uia"]["partial"] for _ in range(2)]
        finally:
            runtime.close()
    checks["fields"] = all(dict(item["fields"]) == EXPECTED for item in partials)
    checks["refusals"] = all(dict(item["failures"]) == REFUSED for item in partials)
    checks["same_identity"] = len({item["capture"]["identity_digest"] for item in partials}) == 1


def run(image: UiaFixtureImage) -> dict[str, Any]:
    """Observe, then retire the fixture; a failed check or cleanup fails the run."""
    checks: dict[str, bool] = {}
    target = native_uia_target(image)
    with Foreground() as foreground:
        try:
            observe_twice(target, checks)
            pid = target._source._binding.identity.pid
        finally:
            target.cleanup()
    checks["never_foreground"] = foreground.samples > 0 and pid not in foreground.owners
    return {"schema": 1, "image_sha256": image.pin.sha256, "checks": checks,
            "foreground_samples": foreground.samples,
            "execution": "passed" if all(checks.values()) else "failed"}


def main(argv: list[str] | None = None) -> int:
    """Default mode only states that nothing ran."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--sha256", required=True, help="independently reviewed executable hash")
    parser.add_argument("--execute", action="store_true", help="run only while native acceptance is resumed")
    args = parser.parse_args(argv)
    image = UiaFixtureImage(PinnedExecutable("acceptance-host", secrets.token_hex(16), "uia-fixture", "1", args.sha256),
                            str(args.build.resolve() / "uia_fixture.exe"), "uia-fixture")
    result = run(image) if args.execute else {"schema": 1, "execution": "not_run"}
    print(json.dumps(result, sort_keys=True))
    return int(result["execution"] == "failed")


if __name__ == "__main__":
    sys.exit(main())
