"""Older tabs ask RBAC before a privileged call, as the newer tabs do (offscreen Qt, fakes only).

The secrets, webhooks, plugins, REST, admin console, audit log and USB
surfaces called the headless core directly, past the executor that checks
each ``AC_*`` command's capability, so a viewer-role session could unlock the
vault, start servers or clear the audit log from the GUI. Each slot now checks
the command its call stands for; a refusal is shown on the tab's
:class:`RefusalLabel`, never raised, and the backend is not reached. Outside
an RBAC scope (the default) nothing changes.
"""
import contextlib
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox  # noqa: E402

from headless._qt_settle import pump_until  # noqa: E402
from je_auto_control.gui import plugins_tab, secrets_tab  # noqa: E402
from je_auto_control.gui._authorize import RefusalLabel, refusal  # noqa: E402
from je_auto_control.utils.rbac import AuthorizationContext, Role, authorization_scope  # noqa: E402
from je_auto_control.utils.rbac.policy import COMMAND_CAPABILITIES  # noqa: E402


@pytest.fixture(autouse=True)
def qapp(monkeypatch):
    app = QApplication.instance() or QApplication([])
    shown = []
    for box in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, box, lambda *args: shown.append(args[-1]))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("name", True))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("x.json", ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: ("x.json", ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: "plugins")
    app.shown = shown
    return app


class _Recorder:
    """Any backend: every method call is recorded; a few read-only attributes answer."""

    is_initialized = is_unlocked = True
    is_running = False
    bound_address = None

    def __init__(self) -> None:
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append(name)
            return [] if name.startswith(("list", "query")) else None
        return call


@contextlib.contextmanager
def _viewer():
    with authorization_scope(AuthorizationContext("viewer", Role.VIEWER)):
        yield


def _assert_refused(tab, command, backend_calls=()):
    label = tab._refusal  # noqa: SLF001
    assert isinstance(label, RefusalLabel)
    assert command in label.text(), label.text()
    assert not label.isHidden()
    assert list(backend_calls) == []


def _dispose(tab):
    getattr(tab, "dispose", lambda: None)()
    tab.deleteLater()


# --- the helper ---------------------------------------------------------------------------------------------

def test_refusal_names_the_first_refused_command_and_nothing_without_rbac():
    assert refusal("AC_secret_unlock") is None
    with _viewer():
        assert "AC_secret_unlock" in refusal("AC_mcp_tool_search", "AC_secret_unlock")
    with authorization_scope(AuthorizationContext("root", Role.ADMIN)):
        assert refusal("AC_secret_unlock", "AC_load_plugins") is None


def test_an_allowed_call_clears_an_earlier_refusal():
    label = RefusalLabel()
    with _viewer():
        assert not label.allows("AC_secret_lock")
    assert not label.isHidden()
    assert label.allows("AC_secret_lock")
    assert label.isHidden() and label.text() == ""
    label.deleteLater()


# --- secrets ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("slot, command", [
    ("_on_init", "AC_secret_init"), ("_on_unlock", "AC_secret_unlock"), ("_on_lock", "AC_secret_lock"),
    ("_on_add", "AC_secret_set"), ("_on_remove", "AC_secret_remove"),
    ("_on_change_passphrase", "AC_secret_init"),
])
def test_the_secrets_tab_refuses_a_viewer(monkeypatch, slot, command):
    vault = _Recorder()
    monkeypatch.setattr(secrets_tab, "default_secret_manager", vault)
    tab = secrets_tab.SecretsTab()
    tab._passphrase.setText("pass")
    tab._list.addItem("name")
    tab._list.setCurrentRow(0)
    vault.calls.clear()
    with _viewer():
        getattr(tab, slot)()
    assert not tab._runs.running
    _assert_refused(tab, command, vault.calls)
    _dispose(tab)


def test_the_secrets_tab_is_unchanged_without_rbac(monkeypatch):
    vault = _Recorder()
    monkeypatch.setattr(secrets_tab, "default_secret_manager", vault)
    tab = secrets_tab.SecretsTab()
    tab._on_lock()
    assert pump_until(lambda: not tab._runs.running)
    assert "lock" in vault.calls
    assert tab._refusal.isHidden()
    _dispose(tab)


# --- plugins ------------------------------------------------------------------------------------------------

def test_the_plugins_tab_refuses_a_viewer(monkeypatch):
    loaded = []
    monkeypatch.setattr(plugins_tab, "load_plugin_directory", loaded.append)
    tab = plugins_tab.PluginsTab()
    tab._dir_input.setText("plugins")
    with _viewer():
        tab._on_load()
    assert not tab._loading.running
    _assert_refused(tab, "AC_load_plugins", loaded)
    _dispose(tab)


def test_the_plugins_tab_loads_off_the_gui_thread_without_rbac(monkeypatch):
    import threading
    seen, registered = [], []
    gui = threading.get_ident()

    def load(path):
        seen.append((path, threading.get_ident() != gui))
        return {"AC_x": print}
    monkeypatch.setattr(plugins_tab, "load_plugin_directory", load)
    monkeypatch.setattr(plugins_tab, "register_plugin_commands", lambda commands: registered.extend(commands) or
                        list(commands))
    tab = plugins_tab.PluginsTab()
    tab._dir_input.setText("plugins")
    tab._on_load()
    assert pump_until(lambda: not tab._loading.running)
    assert seen == [("plugins", True)]
    assert registered == ["AC_x"]
    assert tab._list.count() == 1 and tab._refusal.isHidden()
    _dispose(tab)


# --- every tab names what it needs, for the page banner -----------------------------------------------------

@pytest.mark.parametrize("cls", [secrets_tab.SecretsTab, plugins_tab.PluginsTab])
def test_each_tab_declares_its_required_commands(cls):
    required = getattr(cls, "REQUIRED_COMMANDS", ())
    assert required, cls.__name__
    assert set(required) <= set(COMMAND_CAPABILITIES), cls.__name__
