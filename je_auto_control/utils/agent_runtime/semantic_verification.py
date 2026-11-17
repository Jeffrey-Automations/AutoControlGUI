"""Compare fresh semantic readback with a confirmed operation's original target witness."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.receipts import effective_actions
from je_auto_control.utils.agent_runtime.semantic_target import (
    SemanticSnapshot, _fields, _identifier,
)

_PROVENANCE = ("target_id", "identity_digest", "adapter_id", "schema_version", "source")


def validate_semantic_clause(clause: Mapping[str, Any]) -> None:
    """Require a named task command and bounded expected scalar fields, never addresses."""
    if set(clause) != {"kind", "tool", "fields"} or clause["kind"] != "semantic":
        raise AgentTaskError("semantic completion requires exactly kind, tool and fields")
    _identifier(clause["tool"])
    _fields(clause["fields"])


def semantic_matches(clause: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]],
                     observation: Mapping[str, Any]) -> bool | None:
    """Compare current fields; missing or changed provenance is unknown."""
    validate_semantic_clause(clause)
    before = _confirmed_witness(receipts, clause["tool"])
    if before is None:
        return None
    current = SemanticSnapshot.from_dict(observation)
    if not _same_target_readback(before, current):
        return None
    fields = dict(current.fields)
    if not set(clause["fields"]) <= set(fields):
        return None
    return all(type(fields[name]) is type(value) and fields[name] == value
               for name, value in clause["fields"].items())


def _confirmed_witness(receipts: Sequence[Mapping[str, Any]], tool: str) -> SemanticSnapshot | None:
    actions = effective_actions(receipts)
    receipt = next((item for item in reversed(actions) if item.get("command") == tool), None)
    if receipt is None or receipt.get("status") != "confirmed":
        return None
    grounding = receipt.get("grounding")
    if not isinstance(grounding, Mapping):
        return None
    witness = grounding.get("semantic")
    if not isinstance(witness, Mapping):
        return None
    return SemanticSnapshot.from_dict(witness)


def _same_target_readback(before: SemanticSnapshot, current: SemanticSnapshot) -> bool:
    if any(getattr(before, key) != getattr(current, key) for key in _PROVENANCE):
        return False
    if before.revision is None or current.revision is None:
        return False
    return (current.revision >= before.revision and current.observation_id != before.observation_id
            and current.started >= before.finished)
