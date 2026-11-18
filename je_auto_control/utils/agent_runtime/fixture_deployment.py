"""Load a bounded, independently pinned host deployment for the fixed schema-one fixture."""
from __future__ import annotations

import secrets
from typing import Any

from .errors import AgentTaskError
from .fixture_target import FixtureImage
from .pinned_deployment import (
    absolute_path as _path, deployment_settings, load_deployment,
    read_artifact as _read, sha256 as _sha256,
)
from ..process_memory.models import MemoryObservationError, _identifier, _positive
from ..process_memory.pe_image import plan_pinned_image
from ..process_memory.windows_launch import PinnedExecutable

_FIELDS = {"schema", "host", "target", "image", "image_sha256", "read_timeout"}


def fixture_settings(value: Any) -> dict[str, str]:
    """Normalize only the host's deployment reference without reading any artifact."""
    try:
        return deployment_settings(value)
    except AgentTaskError:
        raise AgentTaskError("fixture profile requires a pinned absolute configuration") from None


def _image(data: Any) -> FixtureImage:
    if not isinstance(data, dict) or set(data) != _FIELDS:
        raise ValueError("unknown deployment schema")
    _positive(data["schema"], 1)
    _identifier(data["host"])
    _identifier(data["target"])
    timeout = data["read_timeout"]
    if type(timeout) not in (int, float) or not 0 < timeout <= 60:
        raise ValueError("invalid read budget")
    pin = PinnedExecutable(data["host"], secrets.token_hex(16), "fixture", "1", _sha256(data["image_sha256"]))
    path = _path(data["image"])
    baseline = _read(path, 64 << 20)
    plan = plan_pinned_image(baseline, pin)
    if plan.checked_bytes + 72 > 1 << 20:
        raise ValueError("fixture exceeds reader budget")
    return FixtureImage(pin, str(path), baseline, secrets.token_bytes(16), data["target"], timeout)


def load_fixture_image(path: str, expected_sha256: str) -> FixtureImage:
    """Verify exact config bytes before following their image path; never read task or environment settings."""
    try:
        return _image(load_deployment(path, expected_sha256))
    except (AgentTaskError, OSError, ValueError, TypeError, RecursionError, MemoryObservationError):
        raise AgentTaskError("fixture deployment is invalid") from None
