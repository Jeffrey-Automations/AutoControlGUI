"""Load a bounded, independently pinned host deployment for the fixed schema-one fixture."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any

from .errors import AgentTaskError
from .fixture_target import FixtureImage
from ..process_memory.models import MemoryObservationError, _identifier, _positive
from ..process_memory.pe_image import plan_pinned_image
from ..process_memory.windows_launch import PinnedExecutable

_FIELDS = {"schema", "host", "target", "image", "image_sha256", "read_timeout"}


def _sha256(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid digest")
    return value


def _path(value: Any) -> Path:
    if not isinstance(value, str) or not value or len(value) >= 32768 or "\0" in value:
        raise ValueError("invalid path")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("absolute path required")
    return path


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("invalid artifact")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("artifact grew beyond limit")
    return raw


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


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
        expected = _sha256(expected_sha256)
        raw = _read(_path(path), 16384)
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected):
            raise ValueError("deployment pin mismatch")
        return _image(json.loads(raw, object_pairs_hook=_unique))
    except (OSError, ValueError, TypeError, RecursionError, MemoryObservationError):
        raise AgentTaskError("fixture deployment is invalid") from None
