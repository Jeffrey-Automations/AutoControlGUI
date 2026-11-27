"""Pin service helper evidence to one background process and same-user service lease."""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, ClassVar, Mapping, Sequence

from .errors import AgentTaskError
from .capture_metadata import _identifier
from .models import AgentTaskSpec
from .native_target import NativeDesktopTarget
from .service_observation import SERVICE_TOOLS, ServiceBinding, ServiceObservation, ServiceReceipt
from .service_scope import service_resource, service_scope
from .service_target import ServiceTarget
from .service_worker import parse_service_bootstrap
from .target_config import AgentTargetProfile


class NativeServiceTarget(NativeDesktopTarget, ServiceTarget):
    """Trusted host configuration selects one background helper and its service ownership key."""

    _display_helper: ClassVar[bool] = False

    def __init__(self, *, argv: Sequence[str], service_key: str, target_id: str,
                 config_digest: str, lock_root: Path | None = None,
                 profile: AgentTargetProfile | None = None) -> None:
        self._expected = ServiceBinding(target_id, config_digest, service_scope(service_key), "unbound")
        if profile is not None and (profile.kind != "service" or profile.name != target_id
                or profile.settings["config_sha256"] != config_digest
                or service_scope(profile.settings["service_key"]) != self._expected.scope_id):
            raise AgentTaskError("service profile does not match its fixed helper identity")
        self._binding: ServiceBinding | None = None
        super().__init__(argv=argv, resource_path=service_resource(service_key, lock_root),
                         recovery_probe=lambda: None, profile=profile.to_dict() if profile is not None else None)

    @classmethod
    def from_profile(cls, profile: AgentTargetProfile) -> NativeServiceTarget:
        """Build the fixed service worker without reading configuration or acquiring resources."""
        if profile.kind != "service":
            raise AgentTaskError("service adapter requires a service profile")
        settings = profile.settings
        argv = (sys.executable, "-I", "-u", "-m", "je_auto_control.utils.agent_runtime.service_entrypoint",
                "--config", settings["config_path"], "--config-sha256", settings["config_sha256"])
        return cls(argv=argv, service_key=settings["service_key"], target_id=profile.name,
                   config_digest=settings["config_sha256"], profile=profile)

    def probe(self) -> dict[str, str]:
        """Report missing native evidence without opening configuration or starting a helper."""
        return {"status": "not_supported", "native_evidence": "not_recorded"}

    @property
    def service_binding(self) -> ServiceBinding:
        """Return the original bootstrap binding only after the owned helper confirmed it."""
        if self._binding is None:
            raise AgentTaskError("service helper has not established its owner binding")
        return self._binding

    @property
    def supports_readonly_completion(self) -> bool:
        """Do not claim the desktop/browser completion-helper contract."""
        return False

    def _requires_presence(self, spec: AgentTaskSpec) -> bool:
        return False

    def check_spec(self, spec: AgentTaskSpec) -> None:
        """Reject task-selected identity and input scope before starting a helper."""
        if self._profile is not None:
            self._profile.check(spec)
        if (spec.target != self._expected.target_id or spec.mode != "external" or spec.roots or spec.apps
                or not set(spec.allowed_tools) <= set(SERVICE_TOOLS)):
            raise AgentTaskError("service helper requires its fixed external scope")

    def ready(self, spec: AgentTaskSpec) -> tuple[bool, str]:
        """Check immutable host scope before ordinary owned-helper configuration."""
        self.check_spec(spec)
        return super().ready(spec)

    def _input(self, event: dict[str, Any], *, cleanup: bool = False) -> None:
        raise AgentTaskError("service helpers cannot emit desktop input")

    def _supports_bootstrap(self, reply: Any) -> bool:
        if not super()._supports_bootstrap(reply) or set(reply) != {"protocol", "service"}:
            return False
        try:
            binding = parse_service_bootstrap(reply["service"])
        except (AgentTaskError, TypeError):
            return False
        if not self._matches_host(binding) or self._binding is not None and self._binding != binding:
            return False
        self._binding = binding
        return True

    def _matches_host(self, binding: ServiceBinding) -> bool:
        return (binding.target_id == self._expected.target_id and binding.config_digest == self._expected.config_digest
                and binding.scope_id == self._expected.scope_id)

    def observe(self) -> dict[str, Any]:
        """Reject another helper lifetime or source before publishing a service report."""
        value = ServiceObservation.from_dict(self._request("observe", {}))
        if value.binding != self.service_binding:
            raise AgentTaskError("service helper observation binding changed")
        return value.to_dict()

    def perform(self, name: str, arguments: dict[str, Any]) -> Any:
        """Refuse unobserved commands even through the inherited generic proxy interface."""
        raise AgentTaskError("service commands require observed dispatch")

    def perform_observed(self, name: str, arguments: Mapping[str, Any], *,
                         observation: Mapping[str, Any], operation_id: str) -> ServiceReceipt:
        """Carry the original report and journal ID through the service-only operation."""
        _identifier(operation_id)
        expected = ServiceObservation.from_dict(observation)
        if (expected.binding != self.service_binding or type(name) is not str or name not in SERVICE_TOOLS
                or not isinstance(arguments, Mapping) or arguments):
            raise AgentTaskError("service command exceeds its bound observation scope")
        reply = self._request("perform_service", {"tool": name, "arguments": {},
                              "expected": expected.to_dict(), "operation_id": operation_id})
        receipt = ServiceReceipt.from_dict(reply)
        if (receipt.binding != self.service_binding or receipt.operation_id != operation_id
                or receipt.operation is not SERVICE_TOOLS[name]):
            raise AgentTaskError("service helper replied for another operation")
        return receipt

    def cleanup(self) -> None:
        """Require empty-input cleanup confirmation before proving owned child retirement."""
        channel = self._channel
        if channel is not None and not channel.retired:
            reply = channel.request("cleanup", {"keys": [], "buttons": []}, timeout=3,
                                    check=lambda: None, on_event=self._input)
            if not isinstance(reply, dict) or set(reply) != {"cleaned"} or reply["cleaned"] is not True:
                raise AgentTaskError("service helper cleanup is unconfirmed")
        super().cleanup()
