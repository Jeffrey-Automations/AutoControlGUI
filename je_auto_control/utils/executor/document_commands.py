"""``AC_generate_sop`` and ``AC_generate_code``: written documents keep secret references.

Both commands describe an action list instead of running it. The executor
used to expand their ``actions`` / ``source`` like any argument, so
``${secrets.NAME}`` was written in plaintext into the generated file and the
returned result, and a loop variable the documented steps bind themselves
failed with "Unknown variable". Their document arguments are now deferred by
the executor (``Executor._DEFERRED_COMMAND_KEYS``) and expanded here with
:func:`~je_auto_control.utils.script_vars.interpolate.interpolate_document`:
known ``${var}`` placeholders are substituted as before -- including a
``source`` path built from variables -- while secret references and names not
yet defined stay as written.
"""

from typing import Any, Dict, List, Optional

from je_auto_control.utils.script_vars.interpolate import interpolate_document


def _for_document(value: Any) -> Any:
    """``value`` expanded against the running executor's variables; unchanged outside a run."""
    # pylint: disable-next=import-outside-toplevel  # reason: the executor imports this module
    from je_auto_control.utils.executor.action_executor import _RUNNING
    running = getattr(_RUNNING, "value", None)
    return value if running is None else interpolate_document(value, running.variables)


def generate_sop_command(actions: List[Any], title: str = "Automation Procedure",
                         path: Optional[str] = None) -> Dict[str, Any]:
    """Adapter: build (or write) a step-by-step SOP from an action list."""
    from je_auto_control.utils.process_doc import generate_sop, write_sop
    actions, title = _for_document(actions), _for_document(title)
    if path:
        return {"path": write_sop(actions, path, title=title)}
    return generate_sop(actions, title=title)


def generate_code_command(source: Any, output: Optional[str] = None,
                          target: str = "pytest", name: str = "recorded_flow",
                          style: str = "calls") -> str:
    """Render an action list/file as code, optionally writing a file."""
    from je_auto_control.utils.codegen.codegen import generate_code, generate_code_file
    from je_auto_control.utils.json.json_file import read_action_json
    source = _for_document(source)
    if output:
        return generate_code_file(source, output, target=target, name=name, style=style)
    actions = source if isinstance(source, list) else read_action_json(source)
    return generate_code(actions, target=target, name=name, style=style)


__all__ = ["generate_code_command", "generate_sop_command"]
