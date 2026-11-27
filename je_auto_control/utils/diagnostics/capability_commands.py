"""Shared executor/MCP serialization of a passive capability snapshot."""
from je_auto_control.wrapper.capabilities import BackendContext, probe_capabilities, reset_native_input


def probe_current_capabilities() -> dict[str, object]:
    """Inspect current prerequisites and existing local state without active diagnostics or caller-supplied grants."""
    return probe_capabilities(BackendContext.current()).to_dict()


def reset_current_native_input() -> dict[str, object]:
    """Retire this process's cached Wayland input session/refusal; elsewhere a no-op. Requests no consent."""
    return reset_native_input(BackendContext.current())
