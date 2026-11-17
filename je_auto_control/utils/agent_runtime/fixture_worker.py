"""Private host-launched worker for a pinned Windows fixture, with no task-selected launch settings."""
from __future__ import annotations

import argparse
import sys
from typing import Any, Callable, Sequence

from .errors import AgentTaskError
from .fixture_deployment import load_fixture_image
from .fixture_launch import OwnedChannelLauncher
from .fixture_target import FixtureImage, OwnedFixtureTarget
from .native_worker import NativeWorker
from ..exception.exceptions import AutoControlException
from ..process_memory.windows import WindowsProcessProvider
from ..process_memory.windows_image import WindowsImageObserver


def create_target(image: FixtureImage) -> OwnedFixtureTarget:
    """Bind native owners without launching; managed readiness acquires the pinned process."""
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise AgentTaskError("fixture worker requires 64-bit Windows")
    return OwnedFixtureTarget(
        image, launcher=OwnedChannelLauncher(("--rpc", "--challenge", image.challenge.hex())),
        lease=WindowsImageObserver(), observer=WindowsImageObserver(),
        provider_factory=WindowsProcessProvider)


def serve(path: str, expected_sha256: str, source: Any, sink: Any, *,
          target_factory: Callable[[FixtureImage], OwnedFixtureTarget] = create_target) -> None:
    """Load only the host's pinned deployment, then use the existing serial semantic worker."""
    image = load_fixture_image(path, expected_sha256)
    target = target_factory(image)
    NativeWorker(source, sink, target=target).run()


def main(argv: Sequence[str] | None = None) -> int:
    """Run only as a reviewed host-owned helper; stdout remains the private worker protocol."""
    parser = argparse.ArgumentParser(description="Private pinned fixture worker", allow_abbrev=False)
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    options = parser.parse_args(argv)
    try:
        serve(options.config, options.config_sha256, sys.stdin.buffer, sys.stdout.buffer)
    except (AutoControlException, OSError):
        sys.stderr.write("fixture worker failed\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
