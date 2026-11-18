"""Load the fixed UI fixture deployment without granting task-selected launch settings."""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
import secrets
from typing import Any

from .errors import AgentTaskError
from .pinned_deployment import deployment_settings, load_deployment, read_artifact, sha256
from .uia_owner import UiaFixtureImage
from ..process_memory.models import MemoryObservationError
from ..process_memory.windows_launch import PinnedExecutable

_FIELDS = {"schema", "kind", "host", "target", "image", "image_sha256",
           "max_image_bytes", "attestation_timeout"}


def uia_settings(value: Any) -> dict[str, str]:
    """Accept only the independently pinned host deployment reference."""
    return deployment_settings(value)


def load_uia_image(path: str, expected_sha256: str) -> UiaFixtureImage:
    """Validate config and bounded image bytes before constructing any native owner."""
    try:
        data = load_deployment(path, expected_sha256)
        if (set(data) != _FIELDS or type(data["schema"]) is not int
                or data["schema"] != 1 or data["kind"] != "uia_fixture"):
            raise ValueError("invalid UI deployment schema")
        pin = PinnedExecutable(data["host"], secrets.token_hex(16), "uia-fixture", "1",
                               sha256(data["image_sha256"]))
        image = UiaFixtureImage(pin, data["image"], data["target"],
                               data["max_image_bytes"], data["attestation_timeout"])
        raw = read_artifact(Path(image.path), image.max_image_bytes)
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), pin.sha256):
            raise ValueError("UI image pin mismatch")
        return image
    except (AgentTaskError, OSError, ValueError, TypeError, MemoryObservationError):
        raise AgentTaskError("UI fixture deployment is invalid") from None
