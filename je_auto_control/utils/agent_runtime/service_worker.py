"""Validate service-specific bootstrap, configuration and observed helper dispatch."""
from typing import Any, Mapping

from .context import current_operation
from .errors import AgentTaskError
from .models import AgentTaskSpec
from .policy import TaskPolicy
from .service_target import ServiceTarget
from .service_observation import ServiceBinding
from .target_dispatch import perform


def service_bootstrap(target: ServiceTarget) -> dict[str, Any]:
    """Advertise only the existing immutable owner binding, without service acquisition."""
    return {"version": 1, **target.service_binding.to_dict()}


def configure_service(target: ServiceTarget, payload: Mapping[str, Any]) -> None:
    """Refuse scope overrides before the worker changes its original configuration."""
    if not isinstance(payload, Mapping) or set(payload) != {"spec", "owner"}:
        raise AgentTaskError("service configuration requires only spec and owner")
    owner = payload["owner"]
    if not isinstance(owner, dict) or owner and set(owner) != {"user_id", "role", "store_path"}:
        raise AgentTaskError("service configuration has an invalid owner")
    _validate_owner(owner)
    spec = AgentTaskSpec.from_dict(payload["spec"])
    target.check_spec(spec)
    TaskPolicy(spec)


def perform_service(target: Any, payload: Mapping[str, Any]) -> Any:
    """Send only the closed observed-service request through the pinned managed scope."""
    if not isinstance(target, ServiceTarget):
        raise AgentTaskError("service dispatch requires a service target")
    if not isinstance(payload, Mapping) or set(payload) != {"tool", "arguments", "expected", "operation_id"}:
        raise AgentTaskError("service command has an unknown schema")
    operation = current_operation()
    if operation is None:
        raise AgentTaskError("service dispatch requires a managed worker scope")
    operation.checkpoint()
    TaskPolicy(operation.spec).check(payload["tool"], payload["arguments"])
    result = perform(target, payload["tool"], payload["arguments"], observation=payload["expected"],
                     operation_id=payload["operation_id"])
    operation.checkpoint()
    return result


def _validate_owner(owner: dict[str, Any]) -> None:
    if not owner:
        return
    for key in ("user_id", "role"):
        if not isinstance(owner[key], str) or not owner[key]:
            raise AgentTaskError("service configuration has an invalid owner")
    path = owner["store_path"]
    if path is not None and (not isinstance(path, str) or not path):
        raise AgentTaskError("service configuration has an invalid owner")


def parse_service_bootstrap(value: Any) -> ServiceBinding:
    """Require the exact version-one provenance advertised before acquisition."""
    keys = {"version", "target_id", "config_digest", "scope_id", "binding_id"}
    if not isinstance(value, dict) or set(value) != keys:
        raise AgentTaskError("service bootstrap has an unknown schema")
    if type(value["version"]) is not int or value["version"] != 1:
        raise AgentTaskError("service bootstrap has an unsupported version")
    return ServiceBinding(**{key: item for key, item in value.items() if key != "version"})
