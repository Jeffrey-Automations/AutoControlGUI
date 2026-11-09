"""Cancellable UIA event queue waits with one monotonic deadline."""
import queue
import time
from typing import Any, Dict, Optional

from je_auto_control.utils.exception.cancellation import (
    cancellation_checkpoint, cancellation_timeout,
)

from je_auto_control.utils.executor.run_control import checkpoint, current_stop_token


def wait_for_event(events: queue.Queue, timeout: float) -> Optional[Dict[str, Any]]:
    """Wait for one event while honoring the calling task's cancellation scope."""
    deadline = time.monotonic() + timeout
    while True:
        cancellation_checkpoint()
        checkpoint()
        remaining = max(0.0, deadline - time.monotonic())
        interval = cancellation_timeout(remaining)
        if current_stop_token() is not None:
            interval = min(interval, 0.1)
        try:
            event = events.get(timeout=None if interval == float("inf") else interval)
        except queue.Empty:
            cancellation_checkpoint()
            checkpoint()
            if time.monotonic() >= deadline:
                return None
        else:
            cancellation_checkpoint()
            checkpoint()
            return event
