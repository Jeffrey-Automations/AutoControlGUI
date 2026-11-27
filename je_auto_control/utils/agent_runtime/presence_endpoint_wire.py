"""Carry a presence endpoint through owned launches, choosing the Linux or macOS shape by the metadata itself.

The endpoint is reported by an owned worker and checked again on connect. Which
transport produced it is read from the metadata, not from ``sys.platform``: a
macOS endpoint carries ``"platform": "darwin"`` and the Linux shape carries no
platform tag, so each shape is parsed only by its own closed schema, and a
channel of the other platform refuses the result.
"""
from __future__ import annotations

from typing import Any

from je_auto_control.utils.agent_runtime import presence_pipe_darwin, presence_pipe_linux


def endpoint_to_wire(endpoint: Any) -> dict[str, Any]:
    """Serialize either transport's launch metadata."""
    # pylint: disable-next=import-outside-toplevel  # reason: endpoint types load only when used
    from je_auto_control.utils.agent_runtime.presence_endpoint_darwin import DarwinEndpoint
    if isinstance(endpoint, DarwinEndpoint):
        return presence_pipe_darwin.endpoint_to_wire(endpoint)
    return presence_pipe_linux.endpoint_to_wire(endpoint)


def endpoint_from_wire(value: Any) -> Any:
    """Rebuild launch metadata with the closed schema its shape names."""
    if presence_pipe_darwin.is_darwin_wire(value):
        return presence_pipe_darwin.endpoint_from_wire(value)
    return presence_pipe_linux.endpoint_from_wire(value)
