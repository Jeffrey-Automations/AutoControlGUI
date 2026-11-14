"""The redesigned GUI keeps every feature reachable, opens on the default workflow, and explains what it cannot offer.

Plan F4's parity gate: the three tabs a new window shows, every catalogued tab
still resolving to a class, a feature whose optional extra is missing saying
why and how to install it, and the facade staying Qt-free.
"""
import importlib
import os
import subprocess  # nosec B404  # reason: starts this interpreter on a literal probe
import sys

import pytest

from je_auto_control.gui.tab_registry import TAB_SPECS


def test_a_new_window_opens_on_the_default_workflow():
    assert [spec.key for spec in TAB_SPECS if spec.default_visible] == ["record", "script_builder", "remote_desktop"]


def test_every_catalogued_tab_has_a_unique_key_and_resolves_to_a_class():
    keys = [spec.key for spec in TAB_SPECS]
    assert len(keys) == len(set(keys))
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    unresolved = []
    for spec in TAB_SPECS:
        if not spec.module:                    # built by the main widget itself (Remote Desktop)
            continue
        try:
            module = importlib.import_module(spec.module)
        except ImportError as error:           # an optional extra this environment lacks
            if "webrtc" in spec.module or "remote_desktop" in spec.module:
                continue
            unresolved.append(f"{spec.key}: {error!r}")
            continue
        if not isinstance(getattr(module, spec.class_name, None), type):
            unresolved.append(f"{spec.key}: {spec.module}.{spec.class_name} is not a class")
    assert unresolved == []


def test_a_feature_without_its_extra_says_why_and_how_to_install_it(monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel
    QApplication.instance() or QApplication([])
    from je_auto_control.gui import main_widget

    real_import = __import__

    def no_webrtc(name, *args, **kwargs):
        if name == "je_auto_control.gui.remote_desktop_tab":
            raise ImportError("No module named 'aiortc'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", no_webrtc)
    page = main_widget.AutoControlGUIWidget._build_remote_desktop_tab()
    try:
        text = " ".join(label.text() for label in page.findChildren(QLabel))
        assert "unavailable" in text
        assert "pip install je_auto_control[webrtc]" in text
        assert "aiortc" in text                # the underlying reason, not only the advice
    finally:
        page.deleteLater()


def test_importing_the_package_loads_no_qt():
    probe = "import sys, je_auto_control; print(any('PySide6' in name for name in sys.modules))"
    # argv is this interpreter plus a literal probe. No shell.
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,  # nosec B603  # reason: literal argv
                          check=False, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "False"
