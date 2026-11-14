"""Closing a USB tab mid-enumeration ends the enumeration tool's process.

The enumeration (PowerShell ``Get-PnpDevice``, ``lsusb``, ``system_profiler``)
took up to its 10 s timeout, and a tab closed meanwhile left it running on a
bare worker: CI's page-width probe faulted at exit with that worker still in
``subprocess.run``. It now runs through the cancellable capture helper, and
the tabs run it as a cancellable task.
"""
import subprocess
import sys
import threading
import time
from concurrent.futures import CancelledError

import pytest

from je_auto_control.utils.exception.cancellation import CancellationToken, cancellation_scope
from je_auto_control.utils.usb import usb_devices

_SLOW_TOOL = [sys.executable, "-c", "import time; time.sleep(30)"]


def _tool(code: str) -> list:
    return [sys.executable, "-c", code]


def test_the_tool_output_is_decoded():
    assert usb_devices._run_capture(_tool("print('ok')"), "linux").strip() == "ok"


def test_a_failing_tool_reports_its_exit_code_and_stderr():
    result = usb_devices._run_capture(_tool("import sys; sys.stderr.write('no bus'); sys.exit(3)"), "linux")
    assert result.devices == []
    assert "exit 3: no bus" in result.error


def test_a_missing_tool_is_a_result_not_an_exception():
    result = usb_devices._run_capture(["je-no-such-usb-tool"], "linux")
    assert result.devices == [] and result.error.startswith("je-no-such-usb-tool: ")


def test_a_tool_past_its_timeout_is_a_result(monkeypatch):
    monkeypatch.setattr(usb_devices, "SUBPROCESS_TIMEOUT_S", 0.2)
    result = usb_devices._run_capture(_SLOW_TOOL, "linux")
    assert result.devices == [] and "timed out" in result.error


def test_cancelling_the_scope_ends_the_tool_process():
    token = CancellationToken(task_id=1)
    outcome = []

    def enumerate_in_scope():
        with cancellation_scope(token):
            try:
                usb_devices._run_capture(_SLOW_TOOL, "linux")
            except CancelledError:
                outcome.append(time.monotonic())

    worker = threading.Thread(target=enumerate_in_scope)
    worker.start()
    time.sleep(0.3)
    cancelled_at = time.monotonic()
    token.cancel()
    worker.join(10.0)
    assert outcome, "the enumeration did not end with CancelledError"
    assert outcome[0] - cancelled_at < 5.0


def test_closing_the_usb_devices_tab_ends_the_enumeration(monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from je_auto_control.gui import usb_devices_tab
    from headless._qt_settle import pump_until

    started, ended = threading.Event(), []
    real_popen = subprocess.Popen

    def popen(*args, **kwargs):
        started.set()
        return real_popen(*args, **kwargs)

    def slow_enumeration():
        try:
            return usb_devices._run_capture(_SLOW_TOOL, "linux")
        finally:
            ended.append(time.monotonic())

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(usb_devices_tab, "list_usb_devices", slow_enumeration)
    tab = usb_devices_tab.UsbDevicesTab()
    try:
        tab._refresh()
        assert started.wait(10.0)
        assert tab._listing.running
        closed_at = time.monotonic()
        tab.dispose()
        assert pump_until(lambda: bool(ended), timeout=10.0)
        assert ended[0] - closed_at < 5.0
        assert tab._error_label.text() == ""
    finally:
        tab.deleteLater()
