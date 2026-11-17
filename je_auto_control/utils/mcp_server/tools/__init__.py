"""MCP tool registry for AutoControl.

The package is split into ``_base`` (value types and helpers),
``_handlers`` (adapter functions that bridge to the headless API), and
``_factories`` (per-domain ``MCPTool`` builders). Public consumers
should import only the names re-exported here.
"""
import os
from dataclasses import replace
from typing import Callable, Dict, List, Optional

from je_auto_control.utils.rbac.tool_classification import TOOL_ALIASES

from je_auto_control.utils.mcp_server.tools._base import (
    MCPContent, MCPTool, MCPToolAnnotations, MCPToolDescriptor, MCPToolResult, read_only_env_flag,
)
from je_auto_control.utils.mcp_server.tools._factories import ALL_FACTORIES
from je_auto_control.utils.mcp_server.tools.plugin_tools import (
    make_plugin_tool, register_plugin_tools,
)


# Short, model-friendly aliases for the most-used tools. Each alias is
# registered as an additional MCPTool entry pointing at the same handler.
_DEFAULT_ALIASES = TOOL_ALIASES


#: The canonical tools behind the aliases: the handful most sessions need.
COMMON_TOOL_NAMES = tuple(_DEFAULT_ALIASES.values())
_FACTORY_SUFFIX = "_tools"


def _category_of(factory: Callable[[], List[MCPTool]]) -> str:
    """The category of a factory's tools: its name without ``_tools``."""
    name = getattr(factory, "__name__", "")
    return name[:-len(_FACTORY_SUFFIX)] if name.endswith(_FACTORY_SUFFIX) else name


def _aliases_enabled(explicit: Optional[bool]) -> bool:
    if explicit is not None:
        return bool(explicit)
    raw = os.environ.get("JE_AUTOCONTROL_MCP_ALIASES", "1")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _make_aliases(tools: List[MCPTool]) -> List[MCPTool]:
    by_name: Dict[str, MCPTool] = {tool.name: tool for tool in tools}
    aliases: List[MCPTool] = []
    for short, canonical in _DEFAULT_ALIASES.items():
        target = by_name.get(canonical)
        if target is None:
            continue
        aliases.append(replace(
            target, name=short,
            description=f"Alias for {canonical}: {target.description}",
        ))
    return aliases


def build_default_tool_registry(read_only: Optional[bool] = None,
                                aliases: Optional[bool] = None,
                                ) -> List[MCPTool]:
    """Return the full set of tools the MCP server exposes by default.

    :param read_only: when True, drop every tool whose annotations
        indicate it can mutate state. When None (default), the value
        of ``JE_AUTOCONTROL_MCP_READONLY`` is consulted, so deployments
        can pin the server in safe mode without code changes.
    :param aliases: when True, also register short model-friendly
        aliases (``click``, ``type``, ``screenshot`` ...) pointing at
        the canonical ``ac_*`` tools. Defaults to True; honour
        ``JE_AUTOCONTROL_MCP_ALIASES=0`` to disable globally.
    """
    enforce_read_only = (
        read_only_env_flag() if read_only is None else bool(read_only)
    )
    tools: List[MCPTool] = []
    for factory in ALL_FACTORIES:
        # A factory may name a category itself; otherwise its own name is one.
        category = _category_of(factory)
        tools.extend(tool if tool.category else replace(tool, category=category)
                     for tool in factory())
    if enforce_read_only:
        from je_auto_control.utils.mcp_server.tools._readonly import readonly_tools
        tools = readonly_tools(tools)
    if _aliases_enabled(aliases):
        tools.extend(_make_aliases(tools))
    return tools


__all__ = [
    "COMMON_TOOL_NAMES", "MCPContent", "MCPTool", "MCPToolAnnotations",
    "MCPToolDescriptor", "MCPToolResult", "build_default_tool_registry", "make_plugin_tool",
    "register_plugin_tools",
]
