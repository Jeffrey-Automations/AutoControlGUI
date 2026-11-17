"""Bind a managed fixture profile to one fixed worker and its pinned deployment bootstrap."""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, ClassVar

from .errors import AgentTaskError
from .fixture_observations import FIXTURE_SOURCES
from .semantic_native_target import NativeSemanticTarget
from .target_config import AgentTargetProfile


class NativeFixtureTarget(NativeSemanticTarget):
    """Inert host adapter; settings cannot choose an interpreter, worker, PID or address."""

    observation_sources: ClassVar[tuple[str, ...]] = FIXTURE_SOURCES

    def __init__(self, profile: AgentTargetProfile) -> None:
        if profile.kind != "fixture":
            raise AgentTaskError("fixture adapter requires a fixture profile")
        settings = profile.settings
        argv = (sys.executable, "-I", "-u", "-m", "je_auto_control.utils.agent_runtime.fixture_worker",
                "--config", settings["config_path"], "--config-sha256", settings["config_sha256"])
        resource = Path.home() / ".je_auto_control" / "input_ownership" / ("fixture-" + profile.digest + ".lock")
        super().__init__(argv=argv, resource_path=resource, profile=profile.to_dict())

    def _supports_bootstrap(self, reply: Any) -> bool:
        if not super()._supports_bootstrap(reply) or self._profile is None:
            return False
        expected = {"version": 1, "config_sha256": self._profile.settings["config_sha256"],
                    "target": self._profile.name}
        contract = reply.get("fixture")
        return (isinstance(contract, dict) and contract == expected
                and isinstance(contract.get("version"), int) and not isinstance(contract.get("version"), bool))
