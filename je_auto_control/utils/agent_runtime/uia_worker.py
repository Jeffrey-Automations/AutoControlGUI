"""Serve one pinned UI fixture deployment through a permanently read-only semantic worker."""
from __future__ import annotations

import argparse
import sys
from typing import Any, Callable, Sequence

from .errors import AgentTaskError
from .models import AgentTaskSpec
from .native_worker import NativeWorker
from .parent_watch import start_parent_watch
from .target_config import AgentTargetProfile, check_host_platform
from .uia_deployment import load_uia_image, uia_settings
from .uia_owner import UiaFixtureImage, native_uia_target
from .uia_target import UiaObservationTarget
from ..exception.exceptions import AutoControlException


class UiaFixtureWorker(NativeWorker):
    """Pin configuration before scope mutation and refuse every effect request."""

    def __init__(self, source: Any, sink: Any, *, target: UiaObservationTarget,
                 reference: dict[str, str], target_id: str) -> None:
        super().__init__(source, sink, target=target)
        self._deployment = uia_settings(reference)
        self._deployment_target = target_id

    def _bootstrap(self) -> dict[str, Any]:
        return {**super()._bootstrap(), "uia_fixture": {"version": 1,
                "config_sha256": self._deployment["config_sha256"], "target": self._deployment_target}}

    def _configure_scope(self, payload: dict[str, Any]) -> None:
        profile = AgentTargetProfile.from_dict(payload.get("profile", {}))
        spec = AgentTaskSpec.from_dict(payload["spec"])
        if (profile.kind != "uia_fixture" or profile.name != self._deployment_target
                or dict(profile.settings) != self._deployment or spec.target != profile.name
                or spec.options.get("target_profile") != {"name": profile.name, "digest": profile.digest}):
            raise AgentTaskError("UI fixture profile does not match the loaded deployment")
        profile.check(spec)
        check_host_platform(profile)
        super()._configure_scope(payload)

    def _dispatch(self, operation: str, payload: dict[str, Any]) -> Any:
        if operation in {"perform", "perform_grounded"}:
            raise AgentTaskError("UI fixture worker is read-only")
        return super()._dispatch(operation, payload)


def serve(path: str, expected_sha256: str, source: Any, sink: Any, *,
          target_factory: Callable[[UiaFixtureImage], UiaObservationTarget] = native_uia_target) -> None:
    """Validate fixed deployment bytes before constructing the managed resource owners."""
    image = load_uia_image(path, expected_sha256)
    target = target_factory(image)
    UiaFixtureWorker(source, sink, target=target,
        reference={"config_path": path, "config_sha256": expected_sha256}, target_id=image.target_id).run()


def main(argv: Sequence[str] | None = None) -> int:
    """Use only the host's pinned configuration; stdout belongs to the private worker protocol."""
    parser = argparse.ArgumentParser(description="Private pinned UI fixture worker", allow_abbrev=False)
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    options = parser.parse_args(argv)
    try:
        start_parent_watch()
        serve(options.config, options.config_sha256, sys.stdin.buffer, sys.stdout.buffer)
    except (AutoControlException, OSError):
        sys.stderr.write("UI fixture worker failed\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
