"""No tab keeps itself alive, and dropped tabs do not crash the interpreter at exit.

A Qt connection holds its slot from C++, where Python's collector cannot see
it. A ``lambda`` over ``self`` connected to a child's signal -- the Script
Builder had one per Add-step action, 714 of them -- therefore kept every tab
built alive until exit, where Qt's teardown released the closure, dropped the
tab's last reference inside a C++ destructor and deleted the tab a second time:
the access violation / ``malloc_consolidate`` abort every CI square showed after
all tests passed under PySide6 6.12. The probe runs in a child interpreter so
the exit itself is part of the check.
"""
import os
import subprocess  # nosec B404  # reason: runs this interpreter on a literal probe
import sys

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

_PROBE = r"""
import gc, importlib, os, weakref
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AUTOCONTROL_GUI_SETTINGS"] = "off"
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
# As start_autocontrol_gui() does: the tabs' workers run Python, and a cyclic collection a worker
# triggered could reach a dropped tab's Qt objects (an access violation on Windows 3.11 CI).
from je_auto_control.gui._gui_thread_gc import GuiThreadCollector
collector = GuiThreadCollector(app)
from je_auto_control.gui.tab_registry import TAB_SPECS

def build(spec, delete):
    widget = getattr(importlib.import_module(spec.module), spec.class_name)()
    ref = weakref.ref(widget)
    if delete:
        getattr(widget, "dispose", lambda: None)()
        widget.deleteLater()
    return ref

kept = []
for delete in (False, True):
    for spec in TAB_SPECS:
        if not spec.module:
            continue
        try:
            ref = build(spec, delete)
        except ImportError:
            continue                      # an optional extra this environment lacks
        for _ in range(3):
            app.sendPostedEvents(None, 52)
            app.processEvents()
        gc.collect()
        if ref() is not None:
            kept.append(f"{spec.key} ({'deleted' if delete else 'dropped'})")
print("KEPT:", kept, flush=True)

import je_auto_control.gui.script_builder.builder_tab as builder_tab
def drop():
    builder_tab.ScriptBuilderTab()
for _ in range(20):
    drop()
print("EXITING", flush=True)
"""


def test_no_tab_keeps_itself_alive_and_the_interpreter_exits_cleanly():
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    # argv is this interpreter plus a literal probe. No shell.
    done = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, text=True,  # nosec B603  # reason: literal argv
                          check=False, timeout=300, env=env)
    kept = [line for line in done.stdout.splitlines() if line.startswith("KEPT:")]
    assert kept == ["KEPT: []"], done.stdout + done.stderr
    assert "EXITING" in done.stdout
    assert done.returncode == 0, f"the interpreter crashed at exit (rc {done.returncode}):\n{done.stderr[-2000:]}"
