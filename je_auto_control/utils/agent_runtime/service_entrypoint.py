"""Serve a pinned service deployment through the fixed background worker lifecycle."""
from __future__ import annotations

import argparse
import sys
from typing import Any, Callable, Sequence

from .errors import AgentTaskError
from .models import AgentTaskSpec
from .native_worker import NativeWorker
from .parent_watch import start_parent_watch
from .service_deployment import ServiceDeployment, load_service_deployment, native_service_target, service_settings
from .service_observation import SERVICE_TOOLS
from .service_scope import service_scope
from .service_target import ManagedServiceTarget
from .target_config import AgentTargetProfile, check_host_platform
from ..exception.exceptions import AutoControlException


class PinnedServiceWorker(NativeWorker):
    """Validate profile authority against loaded deployment before changing any worker scope."""

    def __init__(self, source: Any, sink: Any, *, target: ManagedServiceTarget,
                 deployment: ServiceDeployment, reference: dict[str, str]) -> None:
        super().__init__(source, sink, target=target)
        self._deployment = deployment
        self._reference = service_settings({**reference, "service_key": deployment.service_key})
        binding = target.service_binding
        if (binding.target_id != deployment.target_id or binding.config_digest != reference["config_sha256"]
                or binding.scope_id != service_scope(deployment.service_key)):
            raise AgentTaskError("service owner does not match the loaded deployment")

    def _configure_scope(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict) or set(payload) != {"spec", "owner", "profile"}:
            raise AgentTaskError("pinned service configuration requires spec, owner and profile")
        profile = AgentTargetProfile.from_dict(payload["profile"])
        spec = AgentTaskSpec.from_dict(payload["spec"])
        self._check_profile(profile, spec)
        super()._configure_scope({"spec": payload["spec"], "owner": payload["owner"]})

    def _check_profile(self, profile: AgentTargetProfile, spec: AgentTaskSpec) -> None:
        if (profile.kind != "service" or profile.name != self._deployment.target_id
                or spec.target != profile.name
                or spec.options.get("target_profile") != {"name": profile.name, "digest": profile.digest}):
            raise AgentTaskError("service profile does not match the loaded deployment")
        settings = profile.settings
        if (any(settings[key] != self._reference[key] for key in ("config_path", "config_sha256"))
                or service_scope(settings["service_key"]) != service_scope(self._deployment.service_key)
                or not {SERVICE_TOOLS[name] for name in profile.allowed_tools} <= self._deployment.allowed):
            raise AgentTaskError("service profile exceeds its loaded deployment")
        profile.check(spec)
        check_host_platform(profile)


def serve(path: str, expected_sha256: str, source: Any, sink: Any, *,
          target_factory: Callable[[ServiceDeployment, str], ManagedServiceTarget] = native_service_target) -> None:
    """Load pinned configuration before constructing any retained service owners."""
    deployment = load_service_deployment(path, expected_sha256)
    target = target_factory(deployment, expected_sha256)
    PinnedServiceWorker(source, sink, target=target, deployment=deployment,
        reference={"config_path": path, "config_sha256": expected_sha256}).run()


def main(argv: Sequence[str] | None = None) -> int:
    """Accept only the fixed host deployment reference; stdout is private IPC."""
    parser = argparse.ArgumentParser(description="Private pinned service worker", allow_abbrev=False)
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    options = parser.parse_args(argv)
    try:
        start_parent_watch()
        serve(options.config, options.config_sha256, sys.stdin.buffer, sys.stdout.buffer)
    except (AutoControlException, OSError):
        sys.stderr.write("Service worker failed\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
