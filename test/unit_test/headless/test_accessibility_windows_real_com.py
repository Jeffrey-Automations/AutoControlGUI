"""The real Windows UI Automation backend over real COM: reads, the walker thread, and the focus-wait stop.

Skipped unless this is Windows with ``comtypes`` installed (the ``accessibility`` extra). Every call
is read-only: nothing is clicked, typed, focused or changed on the desktop.
"""
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="real UI Automation is Windows-only")
pytest.importorskip("comtypes", reason="install the accessibility extra for real UI Automation")

from je_auto_control.utils.accessibility import accessibility_api  # noqa: E402  # reason: after the skip gate
from je_auto_control.utils.accessibility.walker import _WALKER  # noqa: E402  # reason: after the skip gate
from je_auto_control.utils.ax_events.ax_events import wait_for_focus_change  # noqa: E402  # reason: same
from je_auto_control.utils.executor.run_control import ExecutionStopped, stoppable_run  # noqa: E402


@pytest.fixture(autouse=True)
def _real_backend():
    from je_auto_control.utils.accessibility.backends import reset_backend_cache
    reset_backend_cache()
    usable, reason = accessibility_api.accessibility_status()
    if not usable:
        pytest.skip(f"UI Automation is not usable here: {reason}")
    yield
    reset_backend_cache()


def test_reads_work_on_the_callers_thread_and_on_the_walker():
    plain = accessibility_api.list_accessibility_elements(max_results=20)
    with stoppable_run():
        walked = accessibility_api.list_accessibility_elements(max_results=20)
        again = accessibility_api.list_accessibility_elements(max_results=20)
    assert plain and walked and again
    assert _WALKER.thread is not None and _WALKER.thread.is_alive()


def test_a_focus_wait_ends_by_its_timeout_and_unregisters():
    started = time.monotonic()
    wait_for_focus_change(timeout=0.3)  # None, or the element if focus really moved on this live desktop
    wait_for_focus_change(timeout=0.3)  # a second wait would block if the first handler leaked the lock
    assert time.monotonic() - started < 5


def test_a_stop_wakes_a_focus_wait_on_real_com():
    started = time.monotonic()
    with pytest.raises(ExecutionStopped):
        with stoppable_run() as token:
            threading.Timer(0.3, token.stop).start()
            while time.monotonic() - started < 10:  # a real focus change would end one wait; keep waiting
                wait_for_focus_change(timeout=30)
    assert time.monotonic() - started < 5
