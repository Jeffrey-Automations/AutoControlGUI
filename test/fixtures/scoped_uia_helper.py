"""Exercise the managed scoped UIA path with injected objects, never native UI Automation."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test" / "unit_test"))

from headless.test_agent_uia_target import target  # noqa: E402  # test helper imports checkout-only providers
from je_auto_control.utils.agent_runtime.native_worker import NativeWorker  # noqa: E402  # use checkout
from je_auto_control.utils.agent_runtime.parent_watch import start_parent_watch  # noqa: E402  # use checkout

if len(sys.argv) != 2 or sys.argv[1] not in {"partial", "complete", "hang"}:
    raise SystemExit(2)
start_parent_watch()
adapter, _ = target(sys.argv[1])
NativeWorker(sys.stdin.buffer, sys.stdout.buffer, target=adapter).run()
