"""Cancellable UIA event queue waits with one monotonic deadline."""
import queue
import time
from typing import Any, Dict, Optional

from je_auto_control.utils.exception.cancellation import (
    cancellation_checkpoint, cancellation_timeout,
)


def wait_for_event(events: queue.Queue, timeout: float) -> Optional[Dict[str, Any]]:
    """Wait for one event while honoring the calling task's cancellation scope."""
    deadline = time.monotonic() + timeout
    while True:
        cancellation_checkpoint()
        remaining = max(0.0, deadline - time.monotonic())
        interval = cancellation_timeout(remaining)
        try:
            event = events.get(timeout=None if interval == float("inf") else interval)
        except queue.Empty:
            cancellation_checkpoint()
            if time.monotonic() >= deadline:
                return None
        else:
            cancellation_checkpoint()
            return event
