"""Normalize host-declared DOM fields of a managed browser session into the shared observation report."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from typing import Any, Callable, Literal
from uuid import uuid4

from .capture_metadata import CaptureMetadata, _identifier
from .errors import AgentTaskError
from .models import detached
from .observation_report import ObservationReport
from .partial_observation import PartialObservation
from .semantic_snapshot import SemanticSnapshot

DOM_SOURCE = "dom"
DOM_ADAPTER = "webrunner_dom"
DOM_SCHEMA = "1"
_PROPERTIES = ("text", "value", "visible")
# SDK refusals that leave the session usable: a marked-secret, password, hidden or
# file control, or text under a secret marker. Every other SDK failure is sticky
# there (the session is retired), so it is never reported as one field's failure.
_PROTECTED = frozenset({"text_readback_refused", "value_readback_refused"})


@dataclass(frozen=True)
class DomField:
    """One host-reviewed read: a unique CSS selector, an optional frame and a closed property."""

    name: str
    selector: str
    frame: str
    property: Literal["text", "value", "visible"]

    def __post_init__(self) -> None:
        _identifier(self.name)
        for value, empty in ((self.selector, False), (self.frame, True)):
            if (type(value) is not str or (not value and not empty)
                    or len(value.encode("utf-8")) > 4096 or "\0" in value):
                raise AgentTaskError("invalid host DOM field selector")
        if type(self.property) is not str or self.property not in _PROPERTIES:
            raise AgentTaskError("invalid host DOM field property")

    def to_dict(self) -> dict[str, str]:
        """Return the closed host settings form of this field."""
        return {"name": self.name, "selector": self.selector, "frame": self.frame, "property": self.property}


def dom_fields(value: Any) -> tuple[DomField, ...]:
    """Validate the closed ``semantic_fields`` setting of a browser profile."""
    data = detached(value)
    if not isinstance(data, list) or not 1 <= len(data) <= 64:
        raise AgentTaskError("browser semantic fields must be a bounded list")
    fields = []
    for item in data:
        if not isinstance(item, dict) or set(item) - {"frame"} != {"name", "selector", "property"}:
            raise AgentTaskError("browser semantic field has an unknown schema")
        fields.append(DomField(item["name"], item["selector"], item.get("frame", ""), item["property"]))
    if len({item.name for item in fields}) != len(fields):
        raise AgentTaskError("browser semantic fields must have unique names")
    return tuple(sorted(fields, key=lambda item: item.name))


class _FieldFailure(AgentTaskError):
    """One field's fixed failure reason; caught by the capture and never published as text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _reason(error: BaseException) -> str:
    reason = getattr(error, "reason", "")
    return reason if isinstance(reason, str) else ""


class DomSource:
    """Non-owning reader of one managed session; the browser target owns the session and its retirement.

    Identity is the SDK's browser context, so readings from another context
    (a new session, or a retired one) never pass as the same target lifetime.
    The page URL is read before and after the fields: a navigation in between
    makes the whole capture an ``inconsistent_snapshot`` failure. A field whose
    element is absent or not shown is ``not_found`` (the SDK does not tell the two
    apart) and a shown one the SDK refuses to read back is ``protected``; any
    other SDK failure is sticky in the session and raises.
    The DOM has no revision counter, so captures are ``best_effort``.
    """

    def __init__(self, target_id: str, fields: tuple[DomField, ...],
                 clock: Callable[[], float] = time.perf_counter) -> None:
        _identifier(target_id)
        if (type(fields) is not tuple or not 1 <= len(fields) <= 64
                or not all(isinstance(item, DomField) for item in fields)
                or len({item.name for item in fields}) != len(fields)):
            raise AgentTaskError("invalid DOM field contract")
        self._target_id, self._fields, self._clock = target_id, fields, clock

    @property
    def field_scope(self) -> tuple[str, ...]:
        """The immutable host field names this source reports."""
        return tuple(sorted(item.name for item in self._fields))

    def report(self, session: Any, checkpoint: Callable[[], None]) -> ObservationReport:
        """Capture once and wrap the result as a single-source report."""
        started = self._clock()
        value = self.capture(session, checkpoint)
        finished = self._clock()
        return ObservationReport(DOM_SOURCE, ((DOM_SOURCE, value),), started, finished, self.field_scope)

    def capture(self, session: Any, checkpoint: Callable[[], None]) -> SemanticSnapshot | PartialObservation | str:
        """Return complete fields, partial fields with reasons, or a source failure name."""
        identity = self._identity(session)
        started = self._clock()
        before = self._call(lambda: session.url, checkpoint)
        values: list[tuple[str, Any]] = []
        failures: list[tuple[str, str]] = []
        for item in self._fields:
            try:
                values.append((item.name, self._read(session, item, checkpoint)))
            except _FieldFailure as failure:
                failures.append((item.name, failure.reason))
        after = self._call(lambda: session.url, checkpoint)
        finished = self._clock()
        if type(before) is not str or before != after:
            return "inconsistent_snapshot"
        capture = CaptureMetadata(target_id=self._target_id, identity_digest=identity, adapter_id=DOM_ADAPTER,
                                  schema_version=DOM_SCHEMA, source=DOM_SOURCE, revision=None,
                                  consistency="best_effort", observation_id=uuid4().hex,
                                  started=started, finished=finished)
        if failures:
            return PartialObservation(capture, tuple(values), tuple(failures))
        return SemanticSnapshot(target_id=capture.target_id, identity_digest=identity, adapter_id=DOM_ADAPTER,
                                schema_version=DOM_SCHEMA, source=DOM_SOURCE, fields=tuple(values), revision=None,
                                consistency="best_effort", observation_id=capture.observation_id,
                                started=started, finished=finished)

    @staticmethod
    def _identity(session: Any) -> str:
        context = getattr(session, "context_id", None)
        if type(context) is not str or not context or len(context) > 1024:
            raise AgentTaskError("managed browser context identity is unavailable")
        return hashlib.sha256(b"dom-context-v1\0" + context.encode("utf-8")).hexdigest()

    @staticmethod
    def _call(operation: Callable[[], Any], checkpoint: Callable[[], None]) -> Any:
        checkpoint()
        try:
            value = operation()
        except AgentTaskError:
            raise
        except Exception as error:  # noqa: BLE001  # reason: SDK errors are mapped, never leaked
            if _reason(error) in _PROTECTED:
                raise _FieldFailure("protected") from None
            raise AgentTaskError("managed browser semantic read failed") from None
        checkpoint()
        return value

    def _read(self, session: Any, item: DomField, checkpoint: Callable[[], None]) -> Any:
        # visible() reports a missing element as False; text()/read_value() would
        # instead fault the whole session, so presence is always probed first.
        visible = self._call(lambda: session.visible(item.selector, item.frame), checkpoint)
        if type(visible) is not bool:
            raise AgentTaskError("managed browser visibility readback is invalid")
        if item.property == "visible":
            return visible
        if not visible:
            raise _FieldFailure("not_found")
        reader = session.text if item.property == "text" else session.read_value
        value = self._call(lambda: reader(item.selector, item.frame), checkpoint)
        if type(value) is not str or len(value.encode("utf-8")) > 65536:
            raise _FieldFailure("unreadable")
        return value


_VOLATILE = frozenset({"observation_id", "started", "finished"})


def stable_state(report: ObservationReport) -> dict[str, Any]:
    """The report without capture IDs or times, so an unchanged page fingerprints the same.

    The runtime re-observes before an action and compares fingerprints; capture
    metadata would make every observation look changed, while a field value,
    failure reason, status or browser context change still changes it.
    """
    value = report.to_dict()
    for key in ("started", "finished"):
        value.pop(key)
    for source in value["sources"].values():
        for kind in ("snapshot", "partial"):
            if kind in source:
                holder = source[kind]["capture"] if kind == "partial" else source[kind]
                for key in _VOLATILE:
                    holder.pop(key)
    return value
