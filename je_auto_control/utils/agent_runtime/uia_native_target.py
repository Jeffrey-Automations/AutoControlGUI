"""Bind a zero-action UI profile to its fixed worker and exact deployment bootstrap."""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, ClassVar, Mapping, NoReturn

from .errors import AgentTaskError
from .semantic_native_target import NativeSemanticTarget
from .target_config import AgentTargetProfile
from .uia_target import UIA_FIELDS


class NativeUiaFixtureTarget(NativeSemanticTarget):
    """An inert host proxy whose direct semantic action methods also refuse IPC dispatch."""

    observation_sources: ClassVar[tuple[str, ...]] = ("uia",)
    observation_fields: ClassVar[tuple[str, ...]] = UIA_FIELDS

    def __init__(self, profile: AgentTargetProfile) -> None:
        if profile.kind != "uia_fixture":
            raise AgentTaskError("UI fixture adapter requires a zero-action UI profile")
        settings = profile.settings
        argv = (sys.executable, "-I", "-u", "-m", "je_auto_control.utils.agent_runtime.uia_worker",
                "--config", settings["config_path"], "--config-sha256", settings["config_sha256"])
        resource = Path.home() / ".je_auto_control" / "input_ownership" / ("uia-fixture-" + profile.digest + ".lock")
        super().__init__(argv=argv, resource_path=resource, profile=profile.to_dict())

    def _supports_bootstrap(self, reply: Any) -> bool:
        if not super()._supports_bootstrap(reply) or self._profile is None:
            return False
        expected = {"version": 1, "config_sha256": self._profile.settings["config_sha256"],
                    "target": self._profile.name}
        contract = reply.get("uia_fixture")
        return isinstance(contract, dict) and contract == expected and type(contract.get("version")) is int

    def _send_grounded(self, name: str, arguments: Mapping[str, Any],
                       expected: Mapping[str, Any], operation_id: str) -> NoReturn:
        raise AgentTaskError("UI fixture adapter is read-only")

    def probe(self) -> dict[str, str]:
        """Do not inherit desktop dependency claims for this unverified native UI provider."""
        return {"status": "not_supported", "native_evidence": "not_recorded"}
