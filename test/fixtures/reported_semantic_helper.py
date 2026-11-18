"""Serve synthetic multi-source evidence in a hidden helper without native acquisition."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test" / "unit_test"))

from headless.test_agent_observation_report import ReportTarget  # noqa: E402  # test source needs checkout paths
from je_auto_control.utils.agent_runtime.native_worker import NativeWorker  # noqa: E402  # use this checkout
from je_auto_control.utils.agent_runtime.parent_watch import start_parent_watch  # noqa: E402  # use this checkout


def main() -> None:
    """Keep failure selection test-owned and never acquire a desktop or process-memory provider."""
    if sys.argv[1:] not in ([], ["--partial"]):
        raise SystemExit(2)
    target = ReportTarget()
    if sys.argv[1:]:
        target.failure = "partial_read"
    start_parent_watch()
    NativeWorker(sys.stdin.buffer, sys.stdout.buffer, target=target).run()


if __name__ == "__main__":
    main()
