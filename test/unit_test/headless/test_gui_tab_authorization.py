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
from je_auto_control.gui import (  # noqa: E402
    admin_console_tab, audit_log_tab, plugins_tab, rbac_users_panel, rest_api_tab, secrets_tab, usb_devices_tab,
    usb_passthrough_panel, webhooks_tab,
)
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


# --- webhooks -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("slot, command", [
    ("_on_start", "AC_webhook_start"), ("_on_stop", "AC_webhook_stop"),
    ("_on_register", "AC_webhook_add"), ("_on_remove", "AC_webhook_remove"),
])
def test_the_webhooks_tab_refuses_a_viewer(monkeypatch, slot, command):
    server = _Recorder()
    monkeypatch.setattr(webhooks_tab, "default_webhook_server", server)
    tab = webhooks_tab.WebhooksTab()
    tab._path_input.setText("/jobs")
    tab._script_input.setText("job.json")
    tab._table.setRowCount(1)
    tab._table.setItem(0, 0, webhooks_tab.QTableWidgetItem("hook-1"))
    tab._table.setCurrentCell(0, 0)
    server.calls.clear()
    with _viewer():
        getattr(tab, slot)()
    assert not tab._server_op.busy
    _assert_refused(tab, command, [call for call in server.calls if call != "list_webhooks"])
    _dispose(tab)


def test_the_webhooks_tab_is_unchanged_without_rbac(monkeypatch):
    server = _Recorder()
    monkeypatch.setattr(webhooks_tab, "default_webhook_server", server)
    tab = webhooks_tab.WebhooksTab()
    tab._path_input.setText("/jobs")
    tab._script_input.setText("job.json")
    tab._on_register()
    assert "add" in server.calls and tab._refusal.isHidden()
    _dispose(tab)


# --- REST API and its users ---------------------------------------------------------------------------------

def _rest_registry(monkeypatch):
    registry = _Recorder()
    registry.status = lambda: {"running": True, "url": "http://127.0.0.1:1", "token": "shared"}
    monkeypatch.setattr(rest_api_tab, "rest_api_registry", registry)
    return registry


@pytest.mark.parametrize("slot, command", [
    ("_on_start", "AC_rest_api_start"), ("_on_stop", "AC_rest_api_stop"),
    ("_on_copy_token", "AC_rest_api_status"),
    ("_on_config_export", "AC_config_export"), ("_on_config_import", "AC_config_import"),
])
def test_the_rest_tab_refuses_a_viewer(monkeypatch, slot, command):
    registry, bundles = _rest_registry(monkeypatch), []
    monkeypatch.setattr(rest_api_tab, "export_config_bundle", lambda: bundles.append("export"))
    monkeypatch.setattr(rest_api_tab, "import_config_bundle", lambda bundle: bundles.append("import"))
    copied = []
    monkeypatch.setattr(rest_api_tab.QGuiApplication, "clipboard", lambda: type("C", (), {
        "setText": staticmethod(copied.append)}))
    tab = rest_api_tab.RestApiTab()
    with _viewer():
        getattr(tab, slot)()
    assert not tab._server_op.busy and not tab._config_task.running
    _assert_refused(tab, command, registry.calls + bundles + copied)
    _dispose(tab)


def test_the_rest_tab_does_not_show_the_shared_token_to_a_viewer(monkeypatch):
    _rest_registry(monkeypatch)
    tab = rest_api_tab.RestApiTab()
    assert tab._token_value.text() == "shared"
    with _viewer():
        tab._refresh_status()
    assert "shared" not in tab._token_value.text()
    assert tab._shared_token is None
    assert "AC_rest_api_status" in tab._status_label.text()
    _dispose(tab)


@pytest.mark.parametrize("slot, command", [
    ("_on_add", "AC_user_add"), ("_on_rotate", "AC_user_rotate_token"),
    ("_on_set_role", "AC_user_set_role"), ("_on_remove", "AC_user_remove"), ("refresh", "AC_user_list"),
])
def test_the_rest_users_panel_refuses_a_viewer(monkeypatch, tmp_path, slot, command):
    admin = _Recorder()
    monkeypatch.setattr(rbac_users_panel, "admin", admin)
    panel = rbac_users_panel.RbacUsersPanel()
    panel._path_input.setText(str(tmp_path / "users.json"))
    panel._id_input.setText("alice")
    with _viewer():
        getattr(panel, slot)()
    assert admin.calls == []
    if slot == "refresh":
        assert command in panel._status_label.text()
    else:
        _assert_refused(panel, command)
    panel.deleteLater()


# --- admin console ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("slot, command", [
    ("_on_add", "AC_admin_add_host"), ("_on_remove", "AC_admin_remove_host"),
    ("_on_refresh", "AC_admin_poll"), ("_on_broadcast", "AC_admin_broadcast_execute"),
    ("_refresh_thumbnails", "AC_admin_poll"),
])
def test_the_admin_console_refuses_a_viewer(monkeypatch, slot, command):
    client = _Recorder()
    monkeypatch.setattr(admin_console_tab, "default_admin_console", lambda: client)
    tab = admin_console_tab.AdminConsoleTab()
    tab._thumb_timer.stop()
    tab._label_input.setText("a")
    tab._url_input.setText("http://h:1")
    tab._actions_input.setPlainText('[["AC_get_mouse_position"]]')
    monkeypatch.setattr(tab, "_selected_labels", lambda: ["a"])
    client.calls.clear()
    with _viewer():
        getattr(tab, slot)()
    assert not (tab._polls.running or tab._thumbs.running or tab._broadcasts.running)
    _assert_refused(tab, command, client.calls)
    _dispose(tab)


def test_the_admin_console_hides_its_hosts_from_a_viewer(monkeypatch):
    client = _Recorder()
    client.list_hosts = lambda: [type("H", (), {"label": "a", "base_url": "http://h:1"})()]
    monkeypatch.setattr(admin_console_tab, "default_admin_console", lambda: client)
    tab = admin_console_tab.AdminConsoleTab()
    tab._thumb_timer.stop()
    assert tab._table.rowCount() == 1
    with _viewer():
        tab._refresh_table()
    assert tab._table.rowCount() == 0
    assert "AC_admin_list_hosts" in tab._broadcast_status.text()
    _dispose(tab)


# --- audit log ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("slot, command", [
    ("_refresh", "AC_audit_log_list"), ("_verify", "AC_audit_log_verify"), ("_clear", "AC_audit_log_clear"),
])
def test_the_audit_log_tab_refuses_a_viewer(monkeypatch, slot, command):
    log = _Recorder()
    monkeypatch.setattr(audit_log_tab, "default_audit_log", lambda: log)
    tab = audit_log_tab.AuditLogTab()
    assert pump_until(lambda: not tab._runs.running)
    log.calls.clear()
    with _viewer():
        getattr(tab, slot)()
    assert not tab._runs.running
    _assert_refused(tab, command, log.calls)
    _dispose(tab)


# --- USB ----------------------------------------------------------------------------------------------------

def test_the_usb_devices_tab_refuses_a_viewer(monkeypatch):
    listed = []
    monkeypatch.setattr(usb_devices_tab, "list_usb_devices", lambda: listed.append(1))
    tab = usb_devices_tab.UsbDevicesTab()
    with _viewer():
        tab._refresh()
    assert not tab._listing.running
    _assert_refused(tab, "AC_list_usb_devices", listed)
    _dispose(tab)


@pytest.mark.parametrize("slot, command", [
    ("_enable_sharing", "AC_usb_passthrough_enable"), ("_on_disable_sharing", "AC_usb_passthrough_enable"),
    ("_allow_selected", "AC_usb_acl_"), ("_block_selected", "AC_usb_acl_"),
    ("_export_acl", "AC_usb_acl_export"), ("_import_acl", "AC_usb_acl_import"),
    ("_refresh_local_devices", "AC_list_usb_devices"), ("_list_shared", "AC_usb_loopback_list"),
])
def test_the_usb_sharing_panel_refuses_a_viewer(monkeypatch, tmp_path, slot, command):
    from je_auto_control.utils.usb.passthrough import UsbAcl
    touched = []
    monkeypatch.setattr(usb_passthrough_panel, "enable_usb_passthrough", touched.append)
    monkeypatch.setattr(usb_passthrough_panel, "export_acl_to_file", lambda *args: touched.append("export"))
    monkeypatch.setattr(usb_passthrough_panel, "import_acl_from_file", lambda *args: touched.append("import"))
    monkeypatch.setattr(usb_passthrough_panel, "list_usb_devices", lambda: touched.append("list"))
    acl = UsbAcl(path=tmp_path / "acl.json")
    loop = _Recorder()
    panel = usb_passthrough_panel.UsbPassthroughPanel(acl=acl, loopback_factory=lambda: loop)
    panel._share.loopback = loop if slot in ("_on_disable_sharing", "_list_shared") else None
    panel._local_table.setRowCount(1)
    for column, text in enumerate(("1234", "5678", "pad", "")):
        panel._local_table.setItem(0, column, usb_passthrough_panel.QTableWidgetItem(text))
    panel._local_table.setCurrentCell(0, 0)
    with _viewer():
        getattr(panel, slot)()
    assert not (panel._listing.running or panel._requests.running or panel._share_op.busy)
    _assert_refused(panel, command, touched + loop.calls)
    assert acl.list_rules() == []
    assert panel._loopback is panel._share.loopback
    panel._share.loopback = None
    _dispose(panel)


# --- every tab names what it needs, for the page banner -----------------------------------------------------

@pytest.mark.parametrize("cls", [
    secrets_tab.SecretsTab, plugins_tab.PluginsTab, webhooks_tab.WebhooksTab, rest_api_tab.RestApiTab,
    rbac_users_panel.RbacUsersPanel, admin_console_tab.AdminConsoleTab, audit_log_tab.AuditLogTab,
    usb_devices_tab.UsbDevicesTab, usb_passthrough_panel.UsbPassthroughPanel,
])
def test_each_tab_declares_its_required_commands(cls):
    required = getattr(cls, "REQUIRED_COMMANDS", ())
    assert required, cls.__name__
    assert set(required) <= set(COMMAND_CAPABILITIES), cls.__name__
