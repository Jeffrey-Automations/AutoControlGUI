"""Validate bounded host-pinned deployment bytes before following artifact references."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path, PurePath, PureWindowsPath
import re
import stat
from typing import Any

from .errors import AgentTaskError

_DRIVE = re.compile(r"[A-Za-z]:")


def deployment_settings(value: Any) -> dict[str, str]:
    """Normalize a host configuration reference without opening its file."""
    try:
        if not isinstance(value, dict) or set(value) != {"config_path", "config_sha256"}:
            raise ValueError("invalid deployment reference")
        return {"config_path": str(absolute_path(value["config_path"])),
                "config_sha256": sha256(value["config_sha256"])}
    except (TypeError, ValueError):
        raise AgentTaskError("deployment requires a pinned absolute configuration") from None


def sha256(value: Any) -> str:
    """Require a canonical SHA-256 digest supplied independently by the host."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid digest")
    return value


def is_local_absolute(value: str, path: PurePath) -> bool:
    """Absolute on a local drive without parent traversal: never a UNC share, pipe or device name.

    Opening a UNC path sends the account's NTLM credentials to that host, and a
    pipe name connects to whoever created the pipe first, so neither may name an artifact.
    """
    if not path.is_absolute() or value.startswith(("\\\\", "//")) or ".." in path.parts:
        return False
    return not isinstance(path, PureWindowsPath) or _DRIVE.fullmatch(path.drive) is not None


def absolute_path(value: Any) -> Path:
    """Refuse relative, remote, device or invalid artifact paths before accessing the filesystem."""
    if not isinstance(value, str) or not value or len(value) >= 32768 or "\0" in value:
        raise ValueError("invalid path")
    path = Path(value)
    if not is_local_absolute(value, path):
        raise ValueError("local absolute path required")
    return path


def read_artifact(path: Path, limit: int) -> bytes:
    """Bound both initial size and bytes read from the same regular-file handle."""
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


def load_deployment(path: str, expected_sha256: str) -> dict[str, Any]:
    """Check exact pinned bytes before decoding a duplicate-free configuration object."""
    try:
        expected = sha256(expected_sha256)
        raw = read_artifact(absolute_path(path), 16384)
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected):
            raise ValueError("deployment pin mismatch")
        data = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(data, dict):
            raise ValueError("deployment must be an object")
        return data
    except (OSError, ValueError, TypeError, RecursionError):
        raise AgentTaskError("pinned deployment is invalid") from None
