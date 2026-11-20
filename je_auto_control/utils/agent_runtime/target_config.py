"""Immutable host-reviewed target configuration, distinct from untrusted task options."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.models import AgentTaskSpec, detached, freeze, thaw
from je_auto_control.utils.agent_runtime.pinned_deployment import deployment_settings
from je_auto_control.utils.agent_runtime.policy import TaskPolicy, canonical_spec, validate_root_snapshot
from je_auto_control.utils.path_guard.policy import PathPolicy
from je_auto_control.utils.path_guard.path_guard import PathNotAllowedError


def reviewed_tools(kind: str) -> frozenset[str]:
    """List implemented adapter commands without loading a platform SDK or connecting a target."""
    from je_auto_control.utils.agent_runtime.file_target import FILE_TOOLS
    from je_auto_control.utils.agent_runtime.targets import DESKTOP_TOOLS
    from je_auto_control.utils.agent_runtime.browser_commands import BROWSER_ADAPTER_TOOLS
    from je_auto_control.utils.agent_runtime.fixture_commands import FIXTURE_COMMAND
    from je_auto_control.utils.agent_runtime.service_observation import SERVICE_TOOLS
    kinds = {"files": FILE_TOOLS, "desktop": DESKTOP_TOOLS, "browser": BROWSER_ADAPTER_TOOLS,
             "fixture": frozenset({FIXTURE_COMMAND}), "uia_fixture": frozenset(), "service": frozenset(SERVICE_TOOLS)}
    if kind not in kinds:
        raise AgentTaskError("target kind does not have an implemented managed adapter")
    return kinds[kind]


@dataclass(frozen=True)
class AgentTargetProfile:
    """A named immutable resource definition and host policy ceiling; constructing it never connects."""

    name: str
    kind: str
    allowed_tools: tuple[str, ...]
    roots: tuple[str, ...] = ()
    apps: tuple[str, ...] = ()
    settings: Mapping[str, Any] = field(default_factory=dict)
    _digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,63}", self.name) is None:
            raise AgentTaskError("target profile name must be a bounded plain identifier")
        if self.name in {"local-desktop", "local-files"}:
            raise AgentTaskError("built-in target names are reserved")
        if not isinstance(self.kind, str):
            raise AgentTaskError("target profile kind must be text")
        spec = canonical_spec(AgentTaskSpec.from_dict({"goal": "target profile", "target": self.name,
            "allowed_tools": self.allowed_tools, "roots": self.roots, "apps": self.apps,
            "success_criteria": [{"kind": "actions_complete"}]}))
        TaskPolicy(spec)
        if not set(spec.allowed_tools) <= reviewed_tools(self.kind):
            raise AgentTaskError("target profile tools exceed its reviewed adapter")
        _check_resource_scope(self.kind, spec)
        for name in ("allowed_tools", "roots", "apps"):
            object.__setattr__(self, name, getattr(spec, name))
        object.__setattr__(self, "settings", freeze(_settings(self.kind, self.settings)))
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        object.__setattr__(self, "_digest", hashlib.sha256(encoded).hexdigest())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AgentTargetProfile:
        """Validate finite detached JSON, rejecting unknown fields and executable configuration."""
        if not isinstance(value, Mapping):
            raise AgentTaskError("target profile must be an object")
        try:
            return cls(**detached(value))
        except AgentTaskError:
            raise
        except (TypeError, ValueError) as error:
            raise AgentTaskError("invalid target profile fields") from error

    def to_dict(self) -> dict[str, Any]:
        """Serialize only immutable configuration, excluding runtime connection or credential state."""
        return {"name": self.name, "kind": self.kind, "allowed_tools": list(self.allowed_tools),
                "roots": list(self.roots), "apps": list(self.apps), "settings": thaw(self.settings)}

    @property
    def digest(self) -> str:
        """Return the identity pinned by tasks, trigger templates and skill trials."""
        return self._digest

    def check(self, spec: AgentTaskSpec) -> None:
        """Enforce the immutable host ceiling in addition to task and source-origin policies."""
        validate_root_snapshot(self.roots)
        if "helper_python" in spec.options:
            raise AgentTaskError("helper Python is host configuration, not a task option")
        if self.kind in {"fixture", "uia_fixture", "service"} and {
                "config_path", "config_sha256", "service_key"} & set(spec.options):
            raise AgentTaskError("pinned deployment is host configuration, not a task option")
        if not set(spec.allowed_tools) <= set(self.allowed_tools):
            raise AgentTaskError("task tools exceed the host target profile")
        if not {name.casefold() for name in spec.apps} <= {name.casefold() for name in self.apps}:
            raise AgentTaskError("task applications exceed the host target profile")
        self._check_roots(spec)
        origins = spec.options.get("allowed_origins", ())
        if self.kind == "browser":
            origins = browser_origins(origins)
        if not _origins_within(origins, self.settings.get("allowed_origins", ())):
            raise AgentTaskError("task network origins exceed the host target profile")

    def _check_roots(self, spec: AgentTaskSpec) -> None:
        if spec.roots and not self.roots:
            raise AgentTaskError("target profile grants no filesystem roots")
        try:
            paths = PathPolicy(self.roots)
            for root in spec.roots:
                paths.validate(root, operation="target profile root")
        except PathNotAllowedError as error:
            raise AgentTaskError("task roots exceed the host target profile") from error


def _settings(kind: str, value: Mapping[str, Any]) -> dict[str, Any]:
    data = detached(value)
    if not isinstance(data, dict):
        raise AgentTaskError("target profile settings must be an object")
    if kind in {"fixture", "uia_fixture", "service"}:
        from .service_deployment import service_settings
        parsers = {"fixture": deployment_settings, "uia_fixture": deployment_settings, "service": service_settings}
        return parsers[kind](data)
    allowed = {"allowed_origins"} | ({"platform"} if kind == "desktop" else set())
    if kind == "browser":
        allowed |= {"helper_python", "semantic_fields"}
    if set(data) - allowed:
        raise AgentTaskError("unreviewed target profile settings")
    if kind == "desktop" and data.get("platform") not in {"windows", "macos", "x11", "wayland"}:
        raise AgentTaskError("desktop profiles require an explicit platform")
    _normalize_origins(data)
    if kind == "browser":
        _browser_settings(data, value)
    return data


def _browser_settings(data: dict[str, Any], value: Mapping[str, Any]) -> None:
    data["allowed_origins"] = browser_origins(value.get("allowed_origins", ()))
    if "helper_python" in data:
        # pylint: disable-next=import-outside-toplevel  # reason: optional helper selection stays lazy
        from je_auto_control.utils.agent_runtime.helper_environment import normalize_helper_python
        data["helper_python"] = normalize_helper_python(data["helper_python"])
    if "semantic_fields" in data:
        # pylint: disable-next=import-outside-toplevel  # reason: browser field parsing stays lazy
        from je_auto_control.utils.agent_runtime.dom_observation import dom_fields
        data["semantic_fields"] = [item.to_dict() for item in dom_fields(data["semantic_fields"])]


def _normalize_origins(data: dict[str, Any]) -> None:
    origins = data.get("allowed_origins", [])
    if not isinstance(origins, list) or len(origins) > 50 or not all(isinstance(item, str) for item in origins):
        raise AgentTaskError("target origins must be a bounded list of strings")
    from je_auto_control.utils.agent_runtime.workflow_specs import url_origin
    if origins:
        data["allowed_origins"] = sorted({url_origin(item) for item in origins})


def _check_resource_scope(kind: str, spec: AgentTaskSpec) -> None:
    if kind in {"fixture", "uia_fixture", "service"} and (spec.roots or spec.apps):
        raise AgentTaskError("pinned profiles cannot grant filesystem roots or desktop applications")
    if kind == "files" and (not spec.roots or spec.apps):
        raise AgentTaskError("file target profiles require explicit roots and no desktop applications")
    if kind == "desktop" and not spec.apps:
        raise AgentTaskError("desktop target profiles require explicit application names")
    if kind == "browser":
        _browser_resource_scope(spec)


def _browser_resource_scope(spec: AgentTaskSpec) -> None:
    if spec.apps:
        raise AgentTaskError("browser target profiles cannot grant desktop applications")
    if set(spec.allowed_tools) & {
            "AC_browser_upload", "AC_browser_download", "AC_workflow_manifest"} and not spec.roots:
        raise AgentTaskError("browser file transfers require explicit filesystem roots")


def browser_origins(values: Any) -> list[str]:
    """Normalize exact origin grants without importing or starting the optional browser SDK."""
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 50:
        raise AgentTaskError("browser origins require between one and fifty exact HTTP(S) origins")
    return sorted({_browser_origin(value) for value in values})


def _browser_origin(value: Any) -> str:
    from je_auto_control.utils.agent_runtime.workflow_specs import url_origin
    if not isinstance(value, str) or len(value) > 4096:
        raise AgentTaskError("browser origins must be bounded text")
    try:
        parsed = urlsplit(value)
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username is not None:
            raise AgentTaskError("browser origin grants cannot contain paths, queries, fragments or credentials")
        return url_origin(value)
    except ValueError:
        raise AgentTaskError("browser origin grant is invalid") from None


def _origins_within(value: Any, allowed: Any) -> bool:
    return (isinstance(value, (tuple, list)) and all(isinstance(item, str) for item in value)
            and set(value) <= set(allowed))


def check_host_platform(profile: AgentTargetProfile) -> None:
    """Reject a resource configured for another OS/session before acquiring native input."""
    if profile.kind == "desktop" and profile.settings["platform"] != desktop_platform():
        raise AgentTaskError("target profile platform does not match this host session")
    if profile.kind in {"fixture", "uia_fixture", "service"} and (sys.platform != "win32" or sys.maxsize <= 2**32):
        raise AgentTaskError("pinned target requires 64-bit Windows")


def desktop_platform() -> str:
    """Identify the configured OS/display session without probing permissions or connecting native resources."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        from je_auto_control.linux_wayland import select_display_server
        return select_display_server()
    return "x11" if sys.platform.startswith(("freebsd", "openbsd", "netbsd")) else "unsupported"
