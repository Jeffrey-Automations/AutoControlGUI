"""Check scope at every step of a read-only capture and the full runtime state at a bounded rate.

A full runtime checkpoint is a durable budget write plus authority queries, around 15 ms on a fast
disk and several hundred on a loaded one. Inside a capture that checks between any two native
calls, those writes alone could spend the capture's own deadline. This is for reads only: the
caller must still run the full checkpoint after the capture and before publishing anything, and a
write keeps the full checkpoint at every step. Where a revocation must also stop the reads that
follow it (process memory), the full checkpoint still precedes each read and this covers only the
metadata queries between them.
"""
from __future__ import annotations

import time
from typing import Callable

INTERVAL = 0.05


def capture_checkpoint(validate: Callable[[], None], full: Callable[[], None]) -> Callable[[], None]:
    """Run ``validate`` on every call; ``full`` on the first and then at most once per interval."""
    last = float("-inf")

    def check() -> None:
        nonlocal last
        validate()
        if time.monotonic() - last >= INTERVAL:
            full()
            last = time.monotonic()
    return check


__all__ = ["INTERVAL", "capture_checkpoint"]
