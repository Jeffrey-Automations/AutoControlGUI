"""Permanently read-only owned helper: observation never upgrades to native input or task execution."""
from __future__ import annotations

import json
import sys
from typing import Any

from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.native_worker import NativeWorker
from je_auto_control.utils.agent_runtime.parent_watch import start_parent_watch
from je_auto_control.utils.executor.dispatch import command_guard
from je_auto_control.wrapper._input_observer import input_observer

# Every route by which a NativeWorker reaches native input, a tool or focus: the operation
# whitelist, configure readiness, the command guard, the input observer and owned cleanup.
_NO_INPUT_PATHS = ("_dispatch", "_operation", "_scoped_operation", "_guard", "_input", "_release_owned")
_PRESENCE_FIELDS = frozenset({"presence", "presence_endpoint"})


def _input_paths_refused(worker: type) -> bool:
    """Whether ``worker`` still uses ReadOnlyWorker's own refusal on every input path."""
    return all(getattr(worker, name) is getattr(ReadOnlyWorker, name) for name in _NO_INPUT_PATHS)


# pylint: disable-next=too-few-public-methods  # reason: one inherited RPC loop with permanently restricted dispatch
class ReadOnlyWorker(NativeWorker):
    """Keep the read-only boundary in the helper, independently of the host's restricted view."""

    def __init__(self, source: Any, sink: Any, *, target: Any = None) -> None:
        super().__init__(source, sink, target=target)
        self._configuration: str | None = None

    def _dispatch(self, operation: str, payload: dict[str, Any]) -> Any:
        if operation == "readonly_capabilities" and payload == {}:
            return {"contract": 1, "input_supported": False}
        if operation not in {"bootstrap", "configure", "observe", "verify_browser", "cleanup"}:
            raise AgentTaskError("read-only helper refuses executable operations")
        return super()._dispatch(operation, payload)

    def _configure_scope(self, payload: dict[str, Any]) -> None:
        if set(payload) - {"spec", "owner", "profile"}:
            raise AgentTaskError("read-only helper cannot replace its configured authority")
        configuration = json.dumps(payload, sort_keys=True, allow_nan=False)
        if self._spec is not None:
            if configuration != self._configuration:
                raise AgentTaskError("read-only helper cannot replace its configured authority")
            return
        super()._configure_scope(payload)
        self._configuration = configuration

    def _configure_presence(self, payload: dict[str, Any]) -> None:
        """Configure a desktop scope without a presence lease, and never accept one.

        The presence binding exists to stop automation when a person touches the desktop. This
        helper has nothing to stop: ``perform`` is outside its operation whitelist, every executor
        command meets ``_guard``, every native input event meets ``_input`` and cleanup accepts only
        empty releases, all of which raise. The exemption holds only while a subclass keeps those
        refusals; one that overrides any of them falls back to the standard presence requirement.
        ``_ready_activity`` is not exempted: nothing here calls it, and it still refuses if reached.
        """
        if _PRESENCE_FIELDS & set(payload):
            raise AgentTaskError("read-only helper cannot take a presence lease")
        if not _input_paths_refused(type(self)):
            super()._configure_presence(payload)

    def _operation(self, operation: str, payload: dict[str, Any]) -> Any:
        if operation == "configure":
            if self._profile_kind == "browser":
                return {"ready": False, "reason": "fresh browser startup is not a read-only observation"}
            ready, reason = self._target.ready(self._spec)
            return {"ready": ready, "reason": reason}
        return super()._operation(operation, payload)

    def _guard(self, _policy: Any, name: str, _arguments: Any,
               _request: Any = None, _semantic: bool = False) -> None:
        raise AgentTaskError(f"read-only observation cannot dispatch {name!r}")

    def _input(self, _event: dict[str, Any]) -> None:
        raise AgentTaskError("read-only helper cannot acknowledge native input")

    def _release_owned(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload != {"keys": [], "buttons": []}:
            raise AgentTaskError("read-only helper cannot inject cleanup input")
        with command_guard(lambda name, arguments: self._guard(None, name, arguments)), input_observer(self._input):
            self._target.cleanup()
        return {"cleaned": True}


def main() -> None:
    """Launch only as an explicit host-owned read-only child, with parent retirement monitoring."""
    start_parent_watch()
    ReadOnlyWorker(sys.stdin.buffer, sys.stdout.buffer).run()


if __name__ == "__main__":
    main()
