"""Every page fits a compact window: no tab forces the workspace to scroll sideways.

Each tab is opened the way the window opens it (so it has its page header and
has been through the fit pass) and its minimum width is read. Widths are
measured in average characters of the window's own label font, so the same
budget holds on Windows' Segoe UI and Linux's wider fallback fonts alike.

``WIDE_PAGES`` lists the tabs not yet reworked to fit, each with the most it
may need. The list only shrinks: a listed tab that now fits, or that grew past
its ceiling, fails here. The probe runs in a child interpreter, like the other
whole-window probes, so the tabs' helper threads never outlive it in this one.
"""
import json
import os
import pathlib
import subprocess  # nosec B404  # reason: runs this file's own probe with a fixed argv
import sys

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

#: The most a page may need, in average characters of the label font (about 460 px in 10 pt Segoe UI):
#: a compact window's width less the navigation rail and a scroll bar.
BUDGET = 72
#: Pages still over the budget, with the most each may need until it is reworked. Empty since the
#: 2026-11-14 rework; a page that needs an entry again needs a reason in Progress.md.
WIDE_PAGES: dict = {}

_PROBE = r"""
import json, os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel
app = QApplication.instance() or QApplication([])
from je_auto_control.gui.theme import prepare_application
prepare_application(app)
from je_auto_control.gui.main_window import AutoControlGUIUI
from je_auto_control.gui.tab_registry import TAB_SPECS
window = AutoControlGUIUI(settings=QSettings(sys.argv[1], QSettings.Format.IniFormat))
window.show()
app.processEvents()
workspace = window.auto_control_gui_widget
probe = QLabel("x", workspace)
probe.ensurePolished()
unit = probe.fontMetrics().horizontalAdvance("abcdefghijklmnopqrstuvwxyz") / 26
widths = {}
for spec in TAB_SPECS:
    workspace.activate_tab(spec.key)
    app.processEvents()
    page = workspace.tabs.currentWidget()
    widths[spec.key] = page.minimumSizeHint().width() / unit if workspace.current_tab_key() == spec.key else -1
sys.stdout.write(json.dumps({"unit": unit, "widths": widths}))
sys.stdout.flush()
os._exit(0)
"""


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    root = pathlib.Path(__file__).resolve().parents[3]
    env = dict(os.environ, PYTHONPATH=str(root), QT_QPA_PLATFORM="offscreen")
    if sys.platform == "win32":
        # The offscreen platform finds no fonts on Windows unless pointed at them,
        # and then measures every label as a row of boxes.
        env.setdefault("QT_QPA_FONTDIR", str(pathlib.Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"))
    settings = tmp_path_factory.mktemp("widths") / "gui.ini"
    done = subprocess.run([sys.executable, "-c", _PROBE, str(settings)],  # nosec B603  # nosemgrep  # reason: fixed argv, no shell
                          capture_output=True, text=True, timeout=240, env=env, cwd=str(root), check=False)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def test_every_tab_was_opened(measured):
    assert measured["unit"] > 0
    assert [key for key, width in measured["widths"].items() if width < 0] == []


def test_every_page_fits_a_compact_window(measured):
    over = {key: round(width) for key, width in measured["widths"].items()
            if width > BUDGET and key not in WIDE_PAGES}
    assert over == {}, f"pages wider than {BUDGET} characters: {over}"


def test_the_list_of_wide_pages_only_shrinks(measured):
    widths = measured["widths"]
    assert set(WIDE_PAGES) <= set(widths), "a listed page is no longer registered"
    fits = sorted(key for key in WIDE_PAGES if widths[key] <= BUDGET)
    assert fits == [], f"these now fit; remove them from WIDE_PAGES: {fits}"
    grew = {key: round(widths[key]) for key in WIDE_PAGES if widths[key] > WIDE_PAGES[key]}
    assert grew == {}, f"these grew past their ceiling: {grew}"
