"""Read-only registry variants with enforced argument restrictions."""
import copy
from collections.abc import Mapping
from dataclasses import replace

from je_auto_control.utils.mcp_server.tools._base import MCPTool
from je_auto_control.utils.rbac.tool_classification import UNREVIEWED_EXTERNAL_TOOLS, argument_capability
from je_auto_control.utils.rbac.users import Capability


def check_readonly_arguments(name: str, arguments: Mapping[str, object]) -> None:
    """Reject known mutating argument branches even without schema validation."""
    if arguments.get("capture_on_fail") or argument_capability(name, arguments) == Capability.DRIVE_INPUT:
        from je_auto_control.utils.exception.exceptions import AutoControlActionException
        raise AutoControlActionException("read-only tool refuses mutating arguments")


def readonly_tools(tools: list[MCPTool]) -> list[MCPTool]:
    """Exclude executable selectors and forbid optional capture writes."""
    result: list[MCPTool] = []
    for tool in tools:
        properties = tool.input_schema.get("properties", {})
        if not tool.annotations.read_only or "adb_path" in properties:
            continue
        if tool.name in UNREVIEWED_EXTERNAL_TOOLS:
            continue
        if "capture_on_fail" in properties:
            schema = copy.deepcopy(tool.input_schema)
            schema["properties"]["capture_on_fail"]["enum"] = [False]
            tool = replace(tool, input_schema=schema)
        result.append(replace(tool, enforce_readonly_arguments=True))
    return result
