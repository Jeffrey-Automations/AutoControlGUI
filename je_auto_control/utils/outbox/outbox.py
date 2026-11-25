"""Transactional outbox: durably buffer events and drain them at-least-once.

``events.cloud_events`` posts immediately and synchronously — a crash between
"did the work" and "sent the event" loses it, and a network blip drops it (no
durability, no retry, no replay). The outbox pattern persists each event and
drains it later with at-least-once delivery and a dead-letter cap.

Sent entries are kept only within a retention bound -- at most ``max_sent``
of them (default 1,000) and none sent more than ``max_sent_age_s`` ago
(default 7 days); either bound may be ``None`` to switch it off. They were
kept for ever, so a long-lived outbox and its file grew without limit.
Pending and failed (dead-letter) entries are never pruned. A sent entry
records when it was sent in an optional ``sent_at`` field; one loaded from an
older file has none and is bounded by count only.

Pure standard library (``json``); imports no ``PySide6``. The delivery ``sink``
is injected and the store is in-memory with JSON persistence, so draining is
fully deterministic in CI.
"""
import json
import math
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from je_auto_control.utils.exception.control_signals import is_run_interruption
from je_auto_control.utils.executor.run_control import ExecutionStopped
from je_auto_control.utils.json_store.json_store import atomic_write_text

Sink = Callable[[Any], Any]

#: How many sent entries are kept by default.
DEFAULT_MAX_SENT = 1000
#: How long, in seconds, a sent entry is kept by default.
DEFAULT_MAX_SENT_AGE_S = 7 * 24 * 3600.0


def _check_max_sent(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"max_sent must be a whole number >= 0 or None, not {value!r}")
    return value


def _check_max_age(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or value < 0:
        raise ValueError(f"max_sent_age_s must be a number >= 0 or None, not {value!r}")
    return float(value)


def _sent_at(entry: Dict[str, Any]) -> Optional[float]:
    """When ``entry`` was sent, or ``None`` (an older file, or a hand edit)."""
    value = entry.get("sent_at")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _send_order(entry: Dict[str, Any]) -> Tuple[bool, float]:
    """Sort key: entries with no ``sent_at`` first, then by when they were sent."""
    stamp = _sent_at(entry)
    return (stamp is not None, stamp or 0.0)


class Outbox:
    """An ordered buffer of events drained to a sink with retry + dead-letter.

    ``max_sent`` and ``max_sent_age_s`` bound how many sent entries are kept,
    and for how long (``None`` switches a bound off); ``clock`` is the time
    source for ``sent_at``. See the module docstring.
    """

    def __init__(self, *, max_sent: Optional[int] = DEFAULT_MAX_SENT,
                 max_sent_age_s: Optional[float] = DEFAULT_MAX_SENT_AGE_S,
                 clock: Callable[[], float] = time.time) -> None:
        self._events: List[Dict[str, Any]] = []
        self._counter = 0
        self._max_sent = _check_max_sent(max_sent)
        self._max_sent_age_s = _check_max_age(max_sent_age_s)
        self._clock = clock
        # One outbox per name is shared by every executor thread. Drains are
        # serialised too: two concurrent drains both sent the same entry.
        self._lock = threading.RLock()

    def enqueue(self, event: Any) -> str:
        """Append ``event`` as pending; return its id."""
        with self._lock:
            self._counter += 1
            entry_id = str(self._counter)
            self._events.append({"id": entry_id, "event": event,
                                 "status": "pending", "attempts": 0})
            return entry_id

    def pending(self) -> List[Dict[str, Any]]:
        """Entries still awaiting successful delivery."""
        with self._lock:
            return [entry for entry in self._events if entry["status"] == "pending"]

    def dead_letters(self) -> List[Dict[str, Any]]:
        """Entries that exhausted their delivery attempts."""
        with self._lock:
            return [entry for entry in self._events if entry["status"] == "failed"]

    def drain(self, sink: Sink, *, max_batch: int = 100,
              max_attempts: int = 5) -> Dict[str, int]:
        """Deliver up to ``max_batch`` pending entries via ``sink``.

        On a sink exception the entry is retried until ``max_attempts``, then
        dead-lettered. Sent entries past the retention bounds are then pruned.
        Returns ``{sent, failed, remaining}``. A stop or cancellation is not a
        failed delivery: it ends the drain and is raised.
        """
        with self._lock:
            result = self._drain(sink, max_batch, max_attempts)
            self.prune_sent()
            return result

    def _drain(self, sink: Sink, max_batch: int,
               max_attempts: int) -> Dict[str, int]:
        sent = 0
        failed = 0
        for entry in self.pending()[:max_batch]:
            entry["attempts"] += 1
            try:
                sink(entry["event"])
            except Exception as error:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # reason: counts as a failed attempt
                if isinstance(error, ExecutionStopped) or is_run_interruption(error):
                    entry["attempts"] -= 1
                    raise
                if entry["attempts"] >= max_attempts:
                    entry["status"] = "failed"
                    entry["error"] = str(error)
                    failed += 1
                continue
            entry["status"] = "sent"
            entry["sent_at"] = self._clock()
            sent += 1
        return {"sent": sent, "failed": failed, "remaining": len(self.pending())}

    def prune_sent(self) -> int:
        """Drop the sent entries past the retention bounds; return how many.

        Pending and failed entries are never dropped. Past ``max_sent`` the
        entries sent first go first; one with no ``sent_at`` counts as oldest.
        """
        with self._lock:
            sent = [entry for entry in self._events if entry["status"] == "sent"]
            dropped = {id(entry) for entry in self._expired(sent)}
            kept = [entry for entry in sent if id(entry) not in dropped]
            dropped.update(id(entry) for entry in self._over_count(kept))
            if dropped:
                self._events = [entry for entry in self._events if id(entry) not in dropped]
            return len(dropped)

    def _over_count(self, sent: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """The entries of ``sent`` beyond ``max_sent``, those sent first."""
        if self._max_sent is None or len(sent) <= self._max_sent:
            return []
        oldest_first = sorted(sent, key=_send_order)  # stable: ties keep their order
        return oldest_first[:len(sent) - self._max_sent]

    def _expired(self, sent: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """The entries of ``sent`` sent longer ago than ``max_sent_age_s``."""
        if self._max_sent_age_s is None:
            return []
        cutoff = self._clock() - self._max_sent_age_s
        return [entry for entry in sent
                if (stamp := _sent_at(entry)) is not None and stamp < cutoff]

    def to_dict(self) -> Dict[str, Any]:
        """Return the outbox state as a plain dict."""
        with self._lock:
            return {"counter": self._counter,
                    "events": [dict(entry) for entry in self._events]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **retention: Any) -> "Outbox":
        """Build an outbox from a :meth:`to_dict` mapping.

        ``retention`` takes the constructor's keyword arguments; its bounds are
        applied to the entries read.
        """
        outbox = cls(**retention)
        outbox._counter = int(data.get("counter", 0))
        outbox._events = [dict(entry) for entry in data.get("events", [])]
        outbox.prune_sent()
        return outbox

    def save(self, path: str) -> str:
        """Persist the outbox to ``path`` as JSON; return the path."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(self.to_dict(), indent=2))
        return str(out)

    @classmethod
    def load(cls, path: str, **retention: Any) -> "Outbox":
        """Load an outbox from a JSON file (``retention`` as in :meth:`from_dict`)."""
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")), **retention)
