"""macOS status snapshots use fake thread state and a constants-only Quartz module."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import je_auto_control


_QUARTZ_CONSTANTS = (
    "kCGEventLeftMouseDown", "kCGEventLeftMouseUp", "kCGEventRightMouseDown",
    "kCGEventRightMouseUp", "kCGEventOtherMouseDown", "kCGEventOtherMouseUp",
    "kCGEventFlagMaskCommand", "kCGEventFlagMaskShift", "kCGEventFlagMaskAlphaShift",
    "kCGEventFlagMaskAlternate", "kCGEventFlagMaskControl", "kCGEventFlagMaskSecondaryFn",
    "kCGEventKeyDown", "kCGEventKeyUp", "kCGEventFlagsChanged", "kCGEventScrollWheel",
    "kCGEventTapDisabledByTimeout", "kCGEventTapDisabledByUserInput",
)


def test_stop_clearing_thread_during_status_read_is_safe(monkeypatch):
    quartz = ModuleType("Quartz")
    for value, name in enumerate(_QUARTZ_CONSTANTS):
        setattr(quartz, name, value)
    path = Path(je_auto_control.__file__).parent / "osx/listener/osx_listener.py"
    spec = importlib.util.spec_from_file_location("_osx_status_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as loading:
        loading.setattr(sys, "platform", "darwin")
        loading.setitem(sys.modules, "Quartz", quartz)
        spec.loader.exec_module(module)

    class StoppingTap(module.OSXInputTap):
        stop_during_read = False

        def __getattribute__(self, name):
            value = super().__getattribute__(name)
            if name == "_thread" and self.stop_during_read:
                self.stop_during_read = False
                self._thread = None
                self._stop.set()
            return value

    tap = StoppingTap()
    assert tap.is_recording is False
    tap._thread = SimpleNamespace(is_alive=lambda: True)
    tap._tap = object()
    assert tap.is_recording is True
    tap.stop_during_read = True
    assert tap.is_recording is False
    assert tap._thread is None
