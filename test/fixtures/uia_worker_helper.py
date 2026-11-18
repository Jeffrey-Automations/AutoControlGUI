"""Run the packaged UI worker with injected image/window owners and no native UI execution."""
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test" / "unit_test"))

import pytest  # noqa: E402  # reason: checkout-only injection helper
from headless.test_agent_uia_owner import setup  # noqa: E402  # reason: checkout-only injection helper
from je_auto_control.utils.agent_runtime import target_config, uia_deployment  # noqa: E402
from je_auto_control.utils.agent_runtime.uia_owner import owned_uia_target  # noqa: E402
from je_auto_control.utils.agent_runtime.uia_worker import serve  # noqa: E402
from je_auto_control.utils.agent_runtime.parent_watch import start_parent_watch  # noqa: E402

if len(sys.argv) != 3:
    raise SystemExit(2)
start_parent_watch()
target_config.sys = SimpleNamespace(platform="win32", maxsize=2**63-1)
uia_deployment.read_artifact = lambda _path, _limit: b"measured image bytes"
patch = pytest.MonkeyPatch()


def factory(image):
    _, _, _, _, _, lease, watch, _, launcher = setup(patch)
    return owned_uia_target(image, launcher=launcher, lease=lease, observer=watch)


try:
    serve(sys.argv[1], sys.argv[2], sys.stdin.buffer, sys.stdout.buffer, target_factory=factory)
finally:
    patch.undo()
