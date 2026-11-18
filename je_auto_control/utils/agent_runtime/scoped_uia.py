"""Read explicit fields beneath one retained-process window inside its owned helper."""
from __future__ import annotations

from dataclasses import dataclass
import sys
import threading
import time
from typing import Any, Callable, Literal
from uuid import uuid4

from .capture_metadata import CaptureMetadata
from .errors import AgentObservationStale, AgentTaskError
from .partial_observation import PartialObservation
from .semantic_snapshot import SemanticSnapshot, _identifier
from .uia_launch import BoundUiaWindow

_PROPERTIES = {"name": 30005, "value": 30045, "enabled": 30010}
_PID, _HWND, _AUTOMATION_ID, _PASSWORD = 30002, 30020, 30011, 30019
def _read_errors() -> tuple[type[BaseException], ...]:
    errors: tuple[type[BaseException], ...] = (OSError, AttributeError, TypeError)
    if sys.platform == "win32":
        # pylint: disable-next=import-outside-toplevel  # reason: COMError exists only on Windows
        from _ctypes import COMError
        return errors + (COMError,)
    return errors


_READ_ERRORS = _read_errors()


class _ReadFailure(AgentTaskError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class UiaField:
    """Host-selected exact automation ID and one read-only scalar property."""

    name: str
    automation_id: str
    property: Literal["name", "value", "enabled"]

    def __post_init__(self) -> None:
        _identifier(self.name)
        if (type(self.automation_id) is not str or not self.automation_id
                or len(self.automation_id.encode("utf-8")) > 1024
                or type(self.property) is not str or self.property not in _PROPERTIES):
            raise AgentTaskError("invalid host UIA field selector")


class ScopedUiaSource:
    """Non-owning COM reader; the helper owner supplies deadline and resource retirement."""

    def __init__(self, binding: BoundUiaWindow, target_id: str, fields: tuple[UiaField, ...],
                 automation: Any, *, budget: int = 4096) -> None:
        _identifier(target_id)
        if not isinstance(binding, BoundUiaWindow):
            raise AgentTaskError("invalid scoped UIA binding")
        if type(budget) is not int or not 1 <= budget <= 4096:
            raise AgentTaskError("invalid scoped UIA budget")
        if (type(fields) is not tuple or not 1 <= len(fields) <= 64
                or not all(isinstance(item, UiaField) for item in fields)):
            raise AgentTaskError("invalid scoped UIA fields")
        if len({item.name for item in fields}) != len(fields):
            raise AgentTaskError("invalid scoped UIA capture contract")
        self._binding, self._target_id, self._fields = binding, target_id, fields
        self._automation, self._budget = automation, budget
        self._thread = threading.current_thread()
        self._root_runtime: tuple[int, ...] | None = None

    @property
    def target_id(self) -> str:
        """Identify the host target whose binding this source reports."""
        return self._target_id

    @property
    def field_scope(self) -> tuple[str, ...]:
        """Expose only the immutable host field names to the report owner."""
        return tuple(sorted(item.name for item in self._fields))

    def _call(self, operation: Callable[[], Any], check: Callable[[], None]) -> Any:
        # Every native call is followed by a check, and capture checks before the first one,
        # so a check separates any two calls; checking again before the next call repeated
        # the same check with no native work in between, and each one is a durable write.
        try:
            value = operation()
        except _READ_ERRORS:
            raise _ReadFailure("unreadable") from None
        check()
        return value

    def _property(self, node: Any, property_id: int, check: Callable[[], None]) -> Any:
        value = self._call(lambda: node.GetCurrentPropertyValueEx(property_id, True), check)
        unsupported = self._call(lambda: self._automation.CheckNotSupported(value), check)
        if type(unsupported) not in (bool, int) or unsupported not in (0, 1):
            raise _ReadFailure("unreadable")
        if unsupported:
            raise _ReadFailure("unsupported")
        return value

    def _pid(self, node: Any, check: Callable[[], None]) -> None:
        pid = self._property(node, _PID, check)
        if type(pid) is not int or pid != self._binding.identity.pid:
            raise AgentObservationStale("UIA element belongs to another process")

    def _root_identity(self, node: Any, check: Callable[[], None]) -> tuple[int, ...]:
        self._pid(node, check)
        hwnd = self._property(node, _HWND, check)
        if type(hwnd) is not int or hwnd != self._binding.hwnd:
            raise AgentObservationStale("UIA root does not match its bound window")
        return self._runtime(node, check)

    def _runtime(self, node: Any, check: Callable[[], None]) -> tuple[int, ...]:
        getter = self._call(lambda: node.GetRuntimeId, check)
        runtime = self._call(getter, check)
        if (not isinstance(runtime, (tuple, list)) or not 1 <= len(runtime) <= 128
                or any(type(part) is not int or not -(2**31) <= part < 2**31 for part in runtime)):
            raise _ReadFailure("unreadable")
        return tuple(runtime)

    def _member(self, node: Any, identity: tuple[int, ...], check: Callable[[], None]) -> None:
        walker = self._call(lambda: self._automation.RawViewWalker, check)
        seen: set[tuple[int, ...]] = set()
        for _ in range(self._budget):
            self._pid(node, check)
            runtime = self._runtime(node, check)
            if runtime == identity:
                if self._root_identity(node, check) != identity:
                    raise AgentObservationStale("UIA ancestry root changed")
                return
            if runtime in seen:
                raise _ReadFailure("budget_exceeded")
            seen.add(runtime)
            node = self._call(lambda: walker.GetParentElement(node), check)
            if not node:
                raise AgentObservationStale("UIA element left the bound window")
        raise _ReadFailure("budget_exceeded")

    def _matches(self, root: Any, identity: tuple[int, ...],
                 check: Callable[[], None]) -> dict[str, list[Any]]:
        matches: dict[str, list[Any]] = {item.automation_id: [] for item in self._fields}
        walker = self._call(lambda: self._automation.RawViewWalker, check)
        pending, visited = [root], 0
        while pending:
            node = pending.pop()
            visited += 1
            if visited > self._budget:
                raise _ReadFailure("budget_exceeded")
            self._member(node, identity, check)
            selector = self._property(node, _AUTOMATION_ID, check)
            if type(selector) is not str:
                raise _ReadFailure("unreadable")
            try:
                selector_size = len(selector.encode("utf-8"))
            except UnicodeEncodeError:
                raise _ReadFailure("unreadable") from None
            if selector_size > 1024:
                raise _ReadFailure("budget_exceeded")
            if selector in matches:
                matches[selector].append(node)
            self._member(node, identity, check)
            child = self._call(lambda: walker.GetFirstChildElement(node), check)
            while child:
                self._member(child, identity, check)
                pending.append(child)
                if visited + len(pending) > self._budget:
                    raise _ReadFailure("budget_exceeded")
                child = self._call(lambda: walker.GetNextSiblingElement(child), check)
        return matches

    def _value(self, node: Any, item: UiaField, identity: tuple[int, ...],
               check: Callable[[], None]) -> str | bool:
        self._member(node, identity, check)
        if self._property(node, _AUTOMATION_ID, check) != item.automation_id:
            raise _ReadFailure("unreadable")
        self._member(node, identity, check)
        if item.property != "enabled":
            self._unprotected(node, check)
        self._member(node, identity, check)
        value = self._property(node, _PROPERTIES[item.property], check)
        self._member(node, identity, check)
        if item.property != "enabled":
            self._unprotected(node, check)
        self._member(node, identity, check)
        if self._property(node, _AUTOMATION_ID, check) != item.automation_id:
            raise _ReadFailure("unreadable")
        self._member(node, identity, check)
        expected = bool if item.property == "enabled" else str
        if type(value) is not expected:
            raise _ReadFailure("unreadable")
        if isinstance(value, str):
            try:
                size = len(value.encode("utf-8"))
            except UnicodeEncodeError:
                raise _ReadFailure("unreadable") from None
            if size > 65536:
                raise _ReadFailure("budget_exceeded")
        return value

    def _unprotected(self, node: Any, check: Callable[[], None]) -> None:
        try:
            protected = self._property(node, _PASSWORD, check)
        except _ReadFailure:
            raise _ReadFailure("protected") from None
        if protected is not False:
            raise _ReadFailure("protected")

    def capture(self, checkpoint: Callable[[], None]) -> SemanticSnapshot | PartialObservation:
        """Retain partial diagnostics; UIA never supplies a checked state revision."""
        if threading.current_thread() is not self._thread:
            raise AgentTaskError("UIA source cannot cross its COM owner thread")
        started = time.perf_counter()
        self._binding.verify(checkpoint)
        identity = None
        checkpoint()
        try:
            root = self._call(lambda: self._automation.ElementFromHandle(self._binding.hwnd), checkpoint)
            identity = self._root_identity(root, checkpoint)
            if self._root_runtime is not None and identity != self._root_runtime:
                raise AgentObservationStale("UIA root changed between captures")
            matches = self._matches(root, identity, checkpoint)
            values, failures = self._collect_fields(matches, identity, checkpoint)
            after = self._call(lambda: self._automation.ElementFromHandle(self._binding.hwnd), checkpoint)
            if self._root_identity(after, checkpoint) != identity:
                raise AgentObservationStale("UIA root changed during capture")
        except _ReadFailure as error:
            identity = None
            values = []
            reason = "budget_exceeded" if error.reason == "budget_exceeded" else "unreadable"
            failures = [(item.name, reason) for item in self._fields]
        self._binding.verify(checkpoint)
        checkpoint()
        if identity is not None:
            self._root_runtime = identity
        metadata = CaptureMetadata(target_id=self._target_id, identity_digest=self._binding.identity.digest,
            adapter_id="scoped-uia", schema_version="1", source="uia", revision=None,
            consistency="best_effort", observation_id=uuid4().hex, started=started, finished=time.perf_counter())
        if failures:
            return PartialObservation(capture=metadata, fields=tuple(values), failures=tuple(failures))
        return SemanticSnapshot(**metadata.to_dict(), fields=tuple(values))

    def _collect_fields(self, matches: dict[str, list[Any]], identity: tuple[int, ...],
                        checkpoint: Callable[[], None]
                        ) -> tuple[list[tuple[str, str | bool]], list[tuple[str, str]]]:
        values: list[tuple[str, str | bool]] = []
        failures: list[tuple[str, str]] = []
        for item in self._fields:
            found = matches[item.automation_id]
            if len(found) != 1:
                failures.append((item.name, "ambiguous" if found else "not_found"))
                continue
            try:
                values.append((item.name, self._value(found[0], item, identity, checkpoint)))
            except _ReadFailure as error:
                failures.append((item.name, error.reason))
        return values, failures
