"""Run real service ownership and worker logic using only injected Python SCM functions."""
import ctypes
import os
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from je_auto_control.utils.agent_runtime.native_worker import NativeWorker
from je_auto_control.utils.agent_runtime.parent_watch import start_parent_watch
from je_auto_control.utils.agent_runtime.service_operations import ServiceOperation
from je_auto_control.utils.agent_runtime.service_scope import service_scope
from je_auto_control.utils.agent_runtime.service_target import ManagedServiceTarget
from je_auto_control.utils.agent_runtime.windows_service import ServiceStatusProcess, WindowsServiceController
from je_auto_control.wrapper._input_observer import input_event


def mark_entered(marker: Path) -> None:
    """Publish the marker whole: a reader polling for the file never sees it empty."""
    staged = marker.with_name(marker.name + ".tmp")
    staged.write_text("entered", encoding="utf-8")
    os.replace(staged, marker)


class Function:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class Api:
    def __init__(self, fault, initial, marker):
        self.fault, self.state, self.marker = fault, initial, marker
        self.OpenSCManagerW = Function(lambda *_: 101)
        self.OpenServiceW = Function(lambda *_: 202)
        self.QueryServiceStatusEx = Function(self.query)
        self.CloseServiceHandle = Function(lambda *_: 1)
        self.StartServiceW = Function(lambda *_: self.change(4))
        self.ControlService = Function(lambda *_: self.change(1))

    def query(self, _handle, _level, output, _size, _needed):
        if self.fault == "query_denied":
            return 0
        raw = ctypes.cast(output, ctypes.POINTER(ServiceStatusProcess)).contents
        raw.service_type, raw.state, raw.controls, raw.pid = 16, self.state, 1, 777
        return 1

    def change(self, state):
        if self.marker is not None:
            mark_entered(self.marker)
        if self.fault == "hang":
            threading.Event().wait(30)
        if self.fault == "input":
            input_event({"kind": "key_press", "keycode": 65, "is_shift": False})
        if self.fault != "no_effect":
            self.state = state
        if self.fault == "crash_after_effect":
            if self.marker is not None:
                self.marker.write_text("effect", encoding="utf-8")
            os._exit(7)
        return 0 if self.fault == "lose_reply" else 1


class Target(ManagedServiceTarget):
    def observe(self):
        value = super().observe()
        if fault == "stale":
            value["started"] = value["finished"] = 0.0
        if fault == "binding":
            value["binding_id"] = "another-binding"
        if fault == "malformed":
            value["status"]["controls_accepted"] = True
        return value


if __name__ == "__main__":
    start_parent_watch()
    fault, target_id, service_key, digest, initial = sys.argv[1:6]
    marker = Path(sys.argv[6]) if len(sys.argv) > 6 else None
    api = Api(fault, int(initial), marker)
    controller = WindowsServiceController(service_key, allowed=frozenset(ServiceOperation),
                                         api=api, last_error=lambda: 5)
    target = Target(target_id, digest, service_scope(service_key), controller, allowed=frozenset(ServiceOperation))
    NativeWorker(sys.stdin.buffer, sys.stdout.buffer, target=target).run()
