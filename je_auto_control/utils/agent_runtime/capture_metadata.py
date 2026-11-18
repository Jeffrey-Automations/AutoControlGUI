"""Validate source provenance and capture intervals without claiming field completeness."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import sys
from typing import Any, Literal, Mapping

from .errors import AgentTaskError
from .models import detached


def _identifier(value: object) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) is None:
        raise AgentTaskError("semantic observation has an invalid identifier")


@dataclass(frozen=True, kw_only=True)
class CaptureMetadata:
    """Immutable identity and timing shared by complete and partial source captures."""

    target_id: str
    identity_digest: str
    adapter_id: str
    schema_version: str
    source: str
    revision: int | None
    consistency: Literal["sequence_checked", "best_effort"]
    observation_id: str
    started: float
    finished: float

    def __post_init__(self) -> None:
        for value in (self.target_id, self.identity_digest, self.adapter_id, self.schema_version,
                      self.source, self.observation_id):
            _identifier(value)
        self._check_revision()
        for timestamp in (self.started, self.finished):
            if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                    or not 0 <= timestamp <= sys.float_info.max):
                raise AgentTaskError("semantic observation has an invalid capture time")
        if self.started > self.finished:
            raise AgentTaskError("semantic observation has an invalid capture interval")

    def _check_revision(self) -> None:
        if self.consistency == "best_effort" and self.revision is None:
            return
        if (self.consistency != "sequence_checked" or isinstance(self.revision, bool)
                or not isinstance(self.revision, int) or not 0 <= self.revision < 2**64
                or self.revision % 2):
            raise AgentTaskError("semantic observation has an invalid checked revision")

    def to_dict(self) -> dict[str, Any]:
        """Return the fixed scalar metadata schema without field values."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CaptureMetadata:
        """Refuse missing or unknown capture metadata before interpreting partial results."""
        data = detached(value)
        keys = {"target_id", "identity_digest", "adapter_id", "schema_version", "source", "revision",
                "consistency", "observation_id", "started", "finished"}
        if not isinstance(data, dict) or set(data) != keys:
            raise AgentTaskError("capture metadata has an unknown schema")
        return cls(**data)
