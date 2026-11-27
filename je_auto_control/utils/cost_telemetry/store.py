"""Append-only JSONL store + roll-up reports for LLM cost telemetry.

Each ``record(...)`` call appends one :class:`CostEvent` to a file
under ``~/.je_auto_control/cost_events.jsonl``. ``summarise()``
groups events by model / provider / day so dashboards and the GUI tab
can render totals without re-implementing aggregation logic.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from je_auto_control.utils.json_store.json_store import append_json_line
from je_auto_control.utils.cost_telemetry.pricing import estimate_usd


@dataclass(frozen=True)
class CostEvent:
    """One LLM API call we billed someone for."""

    timestamp: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_usd: float
    label: Optional[str] = None
    run_id: Optional[str] = None
    user: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CostSummary:
    """Aggregate over a slice of cost events."""

    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_usd: float
    by_model: Dict[str, float]
    by_provider: Dict[str, float]
    by_day: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def default_cost_log_path() -> Path:
    """``~/.je_auto_control/cost_events.jsonl``, resolved at call time."""
    return Path.home() / ".je_auto_control" / "cost_events.jsonl"


class CostStore:
    """Thread-safe append-only JSONL log of :class:`CostEvent` records."""

    def __init__(self, path: Optional[Path] = None) -> None:
        # Only an explicit path is kept; the default is resolved on every
        # use, because this module builds a shared instance while the
        # package imports -- before a test suite's conftest.py can set HOME.
        self._explicit_path: Optional[Path] = (
            Path(path) if path is not None else None)
        self._lock = threading.Lock()

    @property
    def _path(self) -> Path:
        return self._explicit_path or default_cost_log_path()

    @property
    def path(self) -> Path:
        return self._path

    def record(self, *, provider: str, model: str,
               input_tokens: int, output_tokens: int,
               estimated_usd: Optional[float] = None,
               label: Optional[str] = None,
               run_id: Optional[str] = None,
               user: Optional[str] = None,
               ) -> CostEvent:
        """Append + return one cost event. Estimates ``$`` if not given.

        Negative token counts are refused: they were stored as given and
        subtracted from the totals while the cost treated them as zero.
        """
        if int(input_tokens) < 0 or int(output_tokens) < 0:
            raise ValueError("token counts must not be negative")
        cost = (
            float(estimated_usd) if estimated_usd is not None
            else estimate_usd(model, input_tokens, output_tokens)
        )
        event = CostEvent(
            timestamp=_now_iso(),
            provider=str(provider), model=str(model),
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            estimated_usd=cost,
            label=label, run_id=run_id, user=user,
        )
        payload = json.dumps(event.to_dict(), ensure_ascii=False)
        with self._lock:
            append_json_line(self._path, payload)
        return event

    def list_events(self, limit: int = 1000) -> List[CostEvent]:
        """The newest ``limit`` recorded events, oldest first; unreadable lines are skipped."""
        capped = max(0, int(limit))
        return _parse_lines(self._lines()[-capped:]) if capped else []

    def _lines(self) -> List[bytes]:
        """Every stored line, undecoded: a torn write can end inside a UTF-8 sequence."""
        with self._lock:
            try:
                with self._path.open("rb") as fp:
                    return fp.readlines()
            except FileNotFoundError:
                return []

    def clear(self) -> None:
        with self._lock:
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass

    def summarise(self, *, events: Optional[Iterable[CostEvent]] = None,
                  ) -> CostSummary:
        """Roll up ``events``, or every recorded one when omitted.

        Only the newest 1000 were read, so the totals stopped growing there.
        """
        rows = list(events) if events is not None else _parse_lines(self._lines())
        return summarise_events(rows)


def summarise_events(events: Iterable[CostEvent]) -> CostSummary:
    """Aggregate every event by model / provider / day."""
    total_calls = 0
    total_input = 0
    total_output = 0
    total_usd = 0.0
    by_model: Dict[str, float] = {}
    by_provider: Dict[str, float] = {}
    by_day: Dict[str, float] = {}
    for event in events:
        total_calls += 1
        total_input += event.input_tokens
        total_output += event.output_tokens
        total_usd += event.estimated_usd
        by_model[event.model] = by_model.get(event.model, 0.0) + event.estimated_usd
        by_provider[event.provider] = (
            by_provider.get(event.provider, 0.0) + event.estimated_usd
        )
        day = event.timestamp[:10]
        by_day[day] = by_day.get(day, 0.0) + event.estimated_usd
    return CostSummary(
        total_calls=total_calls,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_usd=round(total_usd, 6),
        by_model={k: round(v, 6) for k, v in sorted(by_model.items())},
        by_provider={k: round(v, 6) for k, v in sorted(by_provider.items())},
        by_day={k: round(v, 6) for k, v in sorted(by_day.items())},
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_lines(lines: Iterable[bytes]) -> List[CostEvent]:
    events = (_parse_line(raw) for raw in lines)
    return [event for event in events if event is not None]


def _parse_line(raw: bytes) -> Optional[CostEvent]:
    text = raw.strip()
    if not text:
        return None
    try:
        payload = json.loads(text.decode("utf-8"))
    except ValueError:   # UnicodeDecodeError, JSONDecodeError
        return None
    try:
        event = CostEvent(**payload)
    except TypeError:
        return None
    return event if _well_typed(event) else None


def _well_typed(event: CostEvent) -> bool:
    """Whether the fields a summary adds up and groups by have their types."""
    return (all(isinstance(text, str) for text in (event.timestamp, event.provider, event.model))
            and all(isinstance(count, int) for count in (event.input_tokens, event.output_tokens))
            and isinstance(event.estimated_usd, (int, float)))


default_cost_store = CostStore()


__all__ = [
    "CostEvent", "CostStore", "CostSummary",
    "default_cost_store", "summarise_events",
]
