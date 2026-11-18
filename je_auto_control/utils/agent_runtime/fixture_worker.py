"""Private host-launched worker for a pinned Windows fixture, with no task-selected launch settings."""
from __future__ import annotations

import argparse
import sys
from typing import Any, Callable, Sequence

from .errors import AgentTaskError
from .fixture_deployment import fixture_settings, load_fixture_image
from .fixture_launch import OwnedChannelLauncher
from .fixture_target import FixtureImage, OwnedFixtureTarget
from .native_worker import NativeWorker
from .models import AgentTaskSpec
from .target_config import AgentTargetProfile
from .parent_watch import start_parent_watch
from ..exception.exceptions import AutoControlException
from ..process_memory.pe_image import plan_pinned_image
from ..process_memory.windows import WindowsProcessProvider
from ..process_memory.windows_image import WindowsImageObserver


class FixtureWorker(NativeWorker):
    """Require the configure profile to name the deployment actually loaded at startup."""

    def __init__(self, source: Any, sink: Any, *, target: OwnedFixtureTarget,
                 reference: dict[str, str], target_id: str) -> None:
        super().__init__(source, sink, target=target)
        self._deployment = fixture_settings(reference)
        self._deployment_target = target_id

    def _bootstrap(self) -> dict[str, Any]:
        return {**super()._bootstrap(), "fixture": {"version": 1,
                "config_sha256": self._deployment["config_sha256"], "target": self._deployment_target}}

    def _configure_scope(self, payload: dict[str, Any]) -> None:
        profile = AgentTargetProfile.from_dict(payload.get("profile", {}))
        spec = AgentTaskSpec.from_dict(payload["spec"])
        if (profile.kind != "fixture" or profile.name != self._deployment_target
                or dict(profile.settings) != self._deployment or spec.target != profile.name
                or spec.options.get("target_profile") != {"name": profile.name, "digest": profile.digest}):
            raise AgentTaskError("fixture profile does not match the loaded deployment")
        profile.check(spec)
        super()._configure_scope(payload)


class FixtureInspectionWorker(NativeWorker):
    """Accept only static inspection; never construct a native target or configure actions."""

    def __init__(self, source: Any, sink: Any, *, path: str, expected_sha256: str) -> None:
        super().__init__(source, sink, target=object())
        self._reference = fixture_settings({"config_path": path, "config_sha256": expected_sha256})

    def _dispatch(self, operation: str, payload: dict[str, Any]) -> Any:
        if not isinstance(payload, dict) or payload:
            raise AgentTaskError("fixture inspection requires an empty payload")
        if operation == "bootstrap":
            return {"protocol": 1, "fixture_inspection": 1}
        if operation != "inspect_fixture":
            raise AgentTaskError("fixture inspection operation is not supported")
        image = load_fixture_image(self._reference["config_path"], self._reference["config_sha256"])
        plan = plan_pinned_image(image.baseline, image.pin)
        return {"status": "static_artifacts_ready", "config_sha256": self._reference["config_sha256"],
                "target": image.target_id, "checked_bytes": plan.checked_bytes,
                "native_evidence": "not_recorded", "fixture_execution": "not_run"}


def create_target(image: FixtureImage) -> OwnedFixtureTarget:
    """Bind native owners without launching; managed readiness acquires the pinned process."""
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise AgentTaskError("fixture worker requires 64-bit Windows")
    return OwnedFixtureTarget(
        image, launcher=OwnedChannelLauncher(("--rpc", "--challenge", image.challenge.hex())),
        lease=WindowsImageObserver(), observer=WindowsImageObserver(),
        provider_factory=WindowsProcessProvider)


def serve(path: str, expected_sha256: str, source: Any, sink: Any, *,
          target_factory: Callable[[FixtureImage], OwnedFixtureTarget] = create_target) -> None:
    """Load only the host's pinned deployment, then use the existing serial semantic worker."""
    image = load_fixture_image(path, expected_sha256)
    target = target_factory(image)
    FixtureWorker(source, sink, target=target, reference={"config_path": path, "config_sha256": expected_sha256},
                  target_id=image.target_id).run()


def main(argv: Sequence[str] | None = None) -> int:
    """Run only as a reviewed host-owned helper; stdout remains the private worker protocol."""
    parser = argparse.ArgumentParser(description="Private pinned fixture worker", allow_abbrev=False)
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--inspect", action="store_true")
    options = parser.parse_args(argv)
    try:
        if options.inspect:
            start_parent_watch()
            FixtureInspectionWorker(sys.stdin.buffer, sys.stdout.buffer, path=options.config,
                                    expected_sha256=options.config_sha256).run()
        else:
            serve(options.config, options.config_sha256, sys.stdin.buffer, sys.stdout.buffer)
    except (AutoControlException, OSError):
        sys.stderr.write("fixture worker failed\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
