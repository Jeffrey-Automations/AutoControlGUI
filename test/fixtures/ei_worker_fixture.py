"""Synthetic owned EI child; no native libraries or desktop operations are imported."""
import sys
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from je_auto_control.linux_wayland.ei_worker import EiWorker  # noqa: E402  # reason: load the tested worktree after inserting its root
from je_auto_control.utils.agent_runtime.parent_watch import start_parent_watch  # noqa: E402  # reason: load the tested worktree after inserting its root


class SyntheticBackend:
    """Only process protocol and ownership are exercised by this fixture."""

    is_available = True
    is_connected = False

    def connect(self, **_kwargs):
        self.is_connected = True

    def disconnect(self):
        self.is_connected = False

    def observed_state(self):
        return "available" if self.is_connected else "unverified"

    def press_key(self, code):
        if code == 999:
            os._exit(17)  # synthetic lost reply after accepting the operation
        if code == 998:
            time.sleep(30)  # synthetic stalled native call, retired by the parent

    def __getattr__(self, _name):
        return lambda *_args: None


if __name__ == "__main__":
    start_parent_watch()
    EiWorker(SyntheticBackend).run(sys.stdin.buffer, sys.stdout.buffer)
