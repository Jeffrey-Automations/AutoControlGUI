"""Every registered tab, switched to another language, reads like one built in it (offscreen, in a subprocess).

The probe builds each tab of ``TAB_SPECS`` in English, switches to Japanese
and re-translates it the way the workspace does (shared surfaces, then the
tab's own ``retranslate``), then builds the same tab again in Japanese and
compares every text a user reads: labels, buttons, group titles, tooltips,
placeholders, table and tree headers, the text and tooltip of every table,
tree and list cell, combo entries and tab titles. A text set once at
construction and never registered shows up as a difference.

The texts a tab sets later, from its state, are covered case by case in
``test_gui_state_texts_language.py`` and ``test_gui_remote_texts_language.py``.
The probe runs in a subprocess: the full tab set leaves timers, threads and
listeners behind that must not reach the rest of the suite.
"""
import json
import os
import subprocess  # nosec B404  # reason: runs this test's own probe script
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_PROBE = r"""
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QGroupBox, QLabel, QLineEdit,
                               QListWidget, QMessageBox, QPlainTextEdit, QTableWidget, QTabWidget, QTextEdit,
                               QTreeWidget, QTreeWidgetItemIterator, QWidget)
app = QApplication.instance() or QApplication([])
for box in ("warning", "information", "critical", "question"):
    setattr(QMessageBox, box, staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
from je_auto_control.gui.adaptive.surfaces import retranslate_surfaces
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
from je_auto_control.gui.tab_registry import TAB_SPECS, lazy_factory


def headers(widget):
    if isinstance(widget, QTableWidget):
        return [widget.horizontalHeaderItem(c).text() if widget.horizontalHeaderItem(c) else ""
                for c in range(widget.columnCount())]
    item = widget.headerItem()
    return [item.text(c) for c in range(item.columnCount())]


def cells(widget):
    if isinstance(widget, QTableWidget):
        items = [widget.item(r, c) for r in range(widget.rowCount()) for c in range(widget.columnCount())]
        return [[i.text(), i.toolTip()] if i is not None else None for i in items]
    if isinstance(widget, QListWidget):
        return [[widget.item(r).text(), widget.item(r).toolTip()] for r in range(widget.count())]
    found, walk = [], QTreeWidgetItemIterator(widget)
    while walk.value() is not None:
        item = walk.value()
        found += [[item.text(c), item.toolTip(c)] for c in range(item.columnCount())]
        walk += 1
    return found


def texts(root):
    found = []
    for widget in (root, *root.findChildren(QWidget)):
        found.append(("tip", widget.toolTip()))
        if isinstance(widget, (QLabel, QAbstractButton)):
            found.append(("text", widget.text()))
        elif isinstance(widget, QGroupBox):
            found.append(("title", widget.title()))
        elif isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit)):
            found.append(("placeholder", widget.placeholderText()))
        if isinstance(widget, (QTableWidget, QTreeWidget)):
            found.append(("headers", headers(widget)))
        if isinstance(widget, (QTableWidget, QTreeWidget, QListWidget)):
            found.append(("cells", cells(widget)))
        if isinstance(widget, QComboBox):
            found.append(("items", [widget.itemText(i) for i in range(widget.count())]))
        if isinstance(widget, QTabWidget):
            found.append(("tabs", [widget.tabText(i) for i in range(widget.count())]))
    return found


differences = []
for spec in TAB_SPECS:
    factory = lazy_factory(spec.module or "je_auto_control.gui.remote_desktop.tab",
                           spec.class_name or "RemoteDesktopTab")
    built = []
    try:
        language_wrapper.reset_language("English")
        built.append(factory())
        language_wrapper.reset_language("Japanese")
        retranslate_surfaces(built[0])
        if callable(getattr(built[0], "retranslate", None)):
            built[0].retranslate()
        built.append(factory())
        switched, fresh = texts(built[0]), texts(built[1])
        if len(switched) != len(fresh):
            differences.append([spec.key, "widget count", len(switched), len(fresh)])
        differences += [[spec.key, a, b] for a, b in zip(switched, fresh) if a != b]
    finally:
        for widget in built:
            getattr(widget, "dispose", widget.close)()
            widget.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
print(json.dumps(differences, ensure_ascii=True))
sys.stdout.flush()
os._exit(0)     # the tabs' leftover threads must not hold the exit up
"""


def test_every_tab_reads_like_one_built_in_the_new_language():
    env = dict(os.environ, PYTHONPATH=str(_REPO_ROOT), QT_QPA_PLATFORM="offscreen")
    argv = [sys.executable, "-c", _PROBE]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300, env=env, cwd=str(_REPO_ROOT), check=False)  # nosec B603  # nosemgrep  # reason: this test's own probe, fixed argv
    assert done.returncode == 0, done.stderr[-2000:]
    differences = json.loads(done.stdout.strip().splitlines()[-1])
    assert differences == [], differences
