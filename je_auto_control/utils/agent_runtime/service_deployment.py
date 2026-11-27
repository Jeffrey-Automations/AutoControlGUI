"""Load a closed service deployment while keeping profile construction free of file access."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .errors import AgentTaskError
from .pinned_deployment import deployment_settings, load_deployment
from .service_operations import ServiceOperation
from .service_scope import service_scope
from .service_target import ManagedServiceTarget
from .windows_service import WindowsServiceController


@dataclass(frozen=True)
class ServiceDeployment:
    """One local service and its immutable native control ceiling."""

    target_id: str
    service_key: str
    allowed: frozenset[ServiceOperation]

    def __post_init__(self) -> None:
        if (type(self.target_id) is not str
                or re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,63}", self.target_id) is None):
            raise AgentTaskError("service deployment target is invalid")
        service_scope(self.service_key)
        if (type(self.allowed) is not frozenset or not self.allowed
                or any(type(item) is not ServiceOperation for item in self.allowed)):
            raise AgentTaskError("service deployment operations are invalid")


def service_settings(value: Any) -> dict[str, str]:
    """Validate the pinned reference and service ownership key without reading the file."""
    if not isinstance(value, dict) or set(value) != {"config_path", "config_sha256", "service_key"}:
        raise AgentTaskError("service settings require a pinned deployment and service key")
    service_scope(value["service_key"])
    return {**deployment_settings({key: value[key] for key in ("config_path", "config_sha256")}),
            "service_key": value["service_key"]}


def load_service_deployment(path: str, expected_sha256: str) -> ServiceDeployment:
    """Verify exact pinned bytes before decoding the fixed service and operation scope."""
    try:
        data = load_deployment(path, expected_sha256)
        if (set(data) != {"schema", "kind", "target", "service_key", "operations"}
                or type(data["schema"]) is not int or data["schema"] != 1 or data["kind"] != "service"):
            raise ValueError("invalid service deployment schema")
        return ServiceDeployment(data["target"], data["service_key"], _operations(data["operations"]))
    except (AgentTaskError, TypeError, ValueError):
        raise AgentTaskError("service deployment is invalid") from None


def _operations(value: Any) -> frozenset[ServiceOperation]:
    if (not isinstance(value, list) or not 1 <= len(value) <= 2
            or any(type(item) is not str for item in value) or len(set(value)) != len(value)):
        raise ValueError("invalid service operations")
    return frozenset(ServiceOperation(item) for item in value)


def native_service_target(deployment: ServiceDeployment, digest: str) -> ManagedServiceTarget:
    """Bind the native API without opening SCM handles; managed reads acquire retained ownership."""
    controller = WindowsServiceController(deployment.service_key, allowed=deployment.allowed)
    return ManagedServiceTarget(deployment.target_id, digest, service_scope(deployment.service_key),
                                controller, allowed=deployment.allowed)
