"""The Record tab's "load recording" honours mandatory signing.

It parsed the file with ``read_action_json`` and playback then ran the list
from memory, so with ``JE_AUTOCONTROL_REQUIRE_SIGNED_ACTIONS`` set a tampered
or unsigned recording still played. Loading now goes through the verifying
reader, and playback runs the content that was verified. Input is faked.
"""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from headless._qt_settle import pump_until  # noqa: E402
from je_auto_control.gui import _record_tab as recording  # noqa: E402
from je_auto_control.utils.action_signing import sign_action_file, signer  # noqa: E402

REQUIRE_ENV = "JE_AUTOCONTROL_REQUIRE_SIGNED_ACTIONS"
_SIGNING_ENVS = ("JE_AUTOCONTROL_ACTION_SIGNING_PRIVATE_KEY",
                 "JE_AUTOCONTROL_ACTION_SIGNING_PUBLIC_KEY",
                 "JE_AUTOCONTROL_ACCEPT_LEGACY_ACTION_SIGNATURES")
_SIGNED = [["AC_set_var", {"name": "signed", "value": 1}]]
_OTHER = [["AC_shell_command", {"shell_command": "calc"}]]


@pytest.fixture
def tab(monkeypatch, tmp_path):
    """A Record tab with signing enforced, a fake executor and recorded warnings."""
    QApplication.instance() or QApplication([])
    for name in _SIGNING_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(REQUIRE_ENV, "1")
    monkeypatch.setattr(signer, "_default_key_path", lambda: tmp_path / "home" / "key")
    panel = recording.RecordTab()
    panel.dispatched, panel.warnings = [], []
    monkeypatch.setattr(recording, "execute_action", panel.dispatched.append)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: panel.warnings.append(args[-1]))
    yield panel
    panel.dispose()
    panel.deleteLater()


def _load(panel, monkeypatch, path):
    monkeypatch.setattr(recording.QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    panel._load_record()
    assert pump_until(lambda: not panel._work.running)


def _play(panel):
    panel._playback_record()
    assert pump_until(lambda: not panel._playback_runs.running)


def _recording(tmp_path):
    path = tmp_path / "recording.json"
    path.write_text(json.dumps(_SIGNED), encoding="utf-8")
    sign_action_file(path)
    return path


def test_a_signed_recording_plays_the_content_that_was_verified(tab, monkeypatch, tmp_path):
    path = _recording(tmp_path)
    _load(tab, monkeypatch, path)
    assert tab._record_data == _SIGNED
    path.write_text(json.dumps(_OTHER), encoding="utf-8")   # changed after the check
    _play(tab)
    assert tab.dispatched == [_SIGNED]
    assert tab.warnings == []


def test_a_tampered_recording_is_refused_and_nothing_plays(tab, monkeypatch, tmp_path):
    path = _recording(tmp_path)
    path.write_text(json.dumps(_OTHER), encoding="utf-8")
    _load(tab, monkeypatch, path)
    assert tab._record_data == []
    assert any("failed verification" in str(text) for text in tab.warnings)
    _play(tab)
    assert tab.dispatched == []


def test_an_unsigned_recording_is_refused_and_nothing_plays(tab, monkeypatch, tmp_path):
    path = tmp_path / "unsigned.json"
    path.write_text(json.dumps(_OTHER), encoding="utf-8")
    _load(tab, monkeypatch, path)
    assert tab._record_data == []
    _play(tab)
    assert tab.dispatched == []
