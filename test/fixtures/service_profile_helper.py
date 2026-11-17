"""Exercise the fixed service entrypoint using Python-only injected SCM functions."""
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from service_helper import Api
from je_auto_control.utils.agent_runtime import target_config
from je_auto_control.utils.agent_runtime.parent_watch import start_parent_watch
from je_auto_control.utils.agent_runtime.service_entrypoint import serve
from je_auto_control.utils.agent_runtime.service_scope import service_scope
from je_auto_control.utils.agent_runtime.service_target import ManagedServiceTarget
from je_auto_control.utils.agent_runtime.windows_service import WindowsServiceController


def target_factory(deployment, digest):
    api = Api(sys.argv[3], int(sys.argv[4]), None)
    controller = WindowsServiceController(deployment.service_key, allowed=deployment.allowed,
                                         api=api, last_error=lambda: 5)
    return ManagedServiceTarget(deployment.target_id, digest, service_scope(deployment.service_key),
                                controller, allowed=deployment.allowed)


if __name__ == "__main__":
    target_config.sys = SimpleNamespace(platform="win32", maxsize=2**63 - 1)
    start_parent_watch()
    serve(sys.argv[1], sys.argv[2], sys.stdin.buffer, sys.stdout.buffer, target_factory=target_factory)
