"""Serve the real memory-target assembly over hidden IPC with entirely injected native calls."""
from dataclasses import replace
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test" / "unit_test"))

from headless.test_agent_fixture_target import setup  # noqa: E402  # checkout test modules require the path above
from je_auto_control.utils.agent_runtime.native_worker import NativeWorker  # noqa: E402  # use this checkout


def main() -> None:
    """Keep the synthetic launch identity fresh for each helper process."""
    if sys.argv[1:] not in ([], ["--partial-read"]):
        raise SystemExit(2)
    target, _, _, _, provider, *_ = setup()
    session = uuid4().hex
    target._image = replace(target._image, pin=replace(target._image.pin, session=session),
                            read_timeout=60)
    identity = replace(provider.identity(), session=session)
    provider.identity = lambda: identity
    if sys.argv[1:]:
        original = provider.read

        def short(address, size):
            value = original(address, size)
            return value[:-1] if size == 16 else value

        provider.read = short
    NativeWorker(sys.stdin.buffer, sys.stdout.buffer, target=target).run()


if __name__ == "__main__":
    main()
