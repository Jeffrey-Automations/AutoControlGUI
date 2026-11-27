"""Build LSP ``Diagnostic`` lists for an AutoControl action JSON file.

Two layers of checking:

1. **JSON parse**: a parse failure surfaces as a diagnostic at the
   reported error line, with severity ``Error``;
2. **Schema**: top-level must be a list (or the executor's
   ``{"auto_control": [...]}`` wrapper); each entry must be a 1- or
   2-element list ``[name]`` / ``[name, params]`` where ``name`` is a
   command the executor knows. ``params`` follows the executor's own
   dispatch rule: keyword arguments as an object or positional
   arguments as a list, except that a flow-control block command
   (``AC_loop``, ``AC_sleep`` ...) takes an object only.

Diagnostics are returned in the LSP wire shape — the server hands
them straight to ``textDocument/publishDiagnostics``.
"""
from __future__ import annotations

import json
from typing import AbstractSet, Any, Dict, List, Optional

from autocontrol_lsp.server.commands import (
    block_command_names, known_action_names,
)


_SEVERITY_ERROR = 1
_SEVERITY_WARNING = 2


def diagnostics_for(text: str) -> List[Dict[str, Any]]:
    """Return every problem found in ``text`` as an LSP Diagnostic dict."""
    try:
        data = json.loads(text or "")
    except json.JSONDecodeError as error:
        return [_parse_error_diagnostic(error)]
    return _schema_diagnostics(data)


def _parse_error_diagnostic(error: json.JSONDecodeError) -> Dict[str, Any]:
    line = max(0, int(error.lineno) - 1)
    column = max(0, int(error.colno) - 1)
    return {
        "range": {
            "start": {"line": line, "character": column},
            "end": {"line": line, "character": column + 1},
        },
        "severity": _SEVERITY_ERROR,
        "source": "autocontrol-lsp",
        "message": f"invalid JSON: {error.msg}",
    }


def _schema_diagnostics(data: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    actions = _unwrap(data)
    if actions is None:
        out.append(_root_must_be_list_diagnostic())
        return out
    known = set(known_action_names())
    blocks = block_command_names()
    for index, entry in enumerate(actions):
        problem = _check_entry(entry, known, blocks)
        if problem is None:
            continue
        out.append(_diagnostic_for_entry(index, problem))
    return out


def _unwrap(data: Any) -> Optional[List[Any]]:
    """The action list, bare or in the executor's ``auto_control`` wrapper."""
    if isinstance(data, dict):
        data = data.get("auto_control")
    return data if isinstance(data, list) else None


def _check_entry(entry: Any, known: AbstractSet[str],
                 blocks: AbstractSet[str]) -> Optional[str]:
    if not isinstance(entry, list):
        return "action must be a list of [name] or [name, params]"
    if not entry:
        return "action list cannot be empty"
    problem = _check_name(entry[0], known)
    if problem is not None:
        return problem
    if len(entry) > 2:
        return "action accepts at most [name, params]"
    if len(entry) == 2:
        return _check_params(entry[0], entry[1], blocks)
    return None


def _check_name(name: Any, known: AbstractSet[str]) -> Optional[str]:
    if not isinstance(name, str):
        return f"action name must be a string, got {type(name).__name__}"
    if not name.startswith("AC_"):
        return f"action name {name!r} must start with AC_"
    if name not in known:
        return f"unknown AC_ command: {name!r}"
    return None


def _check_params(name: str, params: Any,
                  blocks: AbstractSet[str]) -> Optional[str]:
    """The executor's rule: ``event(**params)`` or ``event(*params)``."""
    if name in blocks:
        if isinstance(params, dict):
            return None
        return f"params of flow command {name} must be an object"
    if isinstance(params, (dict, list)):
        return None
    return "params must be an object (keyword arguments) or a list (positional)"


def _diagnostic_for_entry(index: int, message: str) -> Dict[str, Any]:
    return {
        "range": {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 1},
        },
        "severity": _SEVERITY_WARNING,
        "source": "autocontrol-lsp",
        "message": f"action[{index}]: {message}",
    }


def _root_must_be_list_diagnostic() -> Dict[str, Any]:
    return {
        "range": {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 1},
        },
        "severity": _SEVERITY_ERROR,
        "source": "autocontrol-lsp",
        "message": "action file must be a JSON list of [name, params] entries",
    }


__all__ = ["diagnostics_for"]
