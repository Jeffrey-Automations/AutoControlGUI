"""Remote-desktop GUI panels (offscreen Qt, fake viewers and hosts).

Quick Connect dialled ``wss://`` without TLS and its popup forwarded no input;
a host that fails IDNA escaped both connect slots; a ticked audio box was
ignored while the Advanced section was collapsed; the viewer's port opened on
1; a session error left the window and the audio player running; the share
text quoted the fields as edited, not as started; the hidden preview kept
decoding; dates before 1970, naive times and odd remote file rows raised.
"""
import os
import ssl
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from je_auto_control.gui.remote_desktop import connection_screen, host_panel, viewer_panel  # noqa: E402
from je_auto_control.utils.remote_desktop.connect_coordinator import parse_target  # noqa: E402
from je_auto_control.utils.remote_desktop.registry import registry  # noqa: E402
from headless._exit_probe import run_probe  # noqa: E402
from headless._qt_settle import settle, settle_op  # noqa: E402


@pytest.fixture(autouse=True)
def qapp(monkeypatch):
    app = QApplication.instance() or QApplication([])
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    monkeypatch.setattr(registry, "_viewer", None)
    monkeypatch.setattr(registry, "_ws_viewer", None)
    monkeypatch.setattr(registry, "_host", None)
    app.warnings = warnings
    return app


class _FakeViewer:
    connected = True
    remote_host_id = None

    def __init__(self, **kwargs):
        self.kwargs, self.sent = kwargs, []

    def connect(self, timeout):
        raise OSError("refused")

    def send_input(self, action):
        self.sent.append(action)


# --- Quick Connect -----------------------------------------------------------------------------------------

def test_quick_connect_dials_wss_with_a_verifying_tls_context(qapp, monkeypatch):
    made = []
    monkeypatch.setattr(connection_screen, "WebSocketDesktopViewer",
                        lambda **kwargs: made.append(_FakeViewer(**kwargs)) or made[-1])
    screen = connection_screen.QuickConnectScreen()
    screen._dispatch_target(parse_target("wss://desk:8443/"), "tok")
    settle(screen)
    context = made[0].kwargs.get("ssl_context")
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert qapp.warnings == ["refused"]


def test_the_quick_connect_popup_forwards_input(qapp, monkeypatch):
    viewer = _FakeViewer()
    monkeypatch.setattr(registry, "_ws_viewer", None)  # restored after the test
    screen = connection_screen.QuickConnectScreen()
    registry.adopt("ws_viewer", viewer, screen._owner)   # the session this screen opened
    screen._open_screen_window("desk")
    window = screen._screen_window
    window.mouse_pressed.emit(3, 4, "mouse_left")
    window.key_pressed.emit("a")
    screen._close_screen_window()
    assert viewer.sent == [{"action": "mouse_move", "x": 3, "y": 4},
                           {"action": "mouse_press", "button": "mouse_left"},
                           {"action": "key_press", "keycode": "a"}]


def test_a_host_that_fails_idna_is_reported_by_both_viewers(qapp):
    screen = connection_screen.QuickConnectScreen()
    screen._connect_target.setText("a..b:5555")
    screen._connect_token.setText("tok")
    screen._connect()
    settle(screen)
    panel = viewer_panel._ViewerPanel()
    panel._host_field.setText("a..b")
    panel._port.setValue(5555)
    panel._token.setText("tok")
    panel._connect()
    settle(panel)
    assert len(qapp.warnings) == 2


_CLOSE_PROBE = """
import gc, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
app = QApplication([])
from je_auto_control.gui.remote_desktop import connection_screen, viewer_panel

def session():
    if sys.argv[1] == "viewer":
        owner = viewer_panel._ViewerPanel()
        owner._ensure_screen_window()
    else:
        owner = connection_screen.QuickConnectScreen()
        owner._open_screen_window("desk")
    owner._close_screen_window()

session()
gc.collect()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
print("flushed", flush=True)
"""


@pytest.mark.parametrize("owner", ["viewer", "quick"])
def test_a_closed_window_outliving_its_owner_does_not_abort(owner):
    # The input connections held the owner, so the window's deferred delete
    # released it, and the owner deleted that window again: Qt aborted.
    done = run_probe(_CLOSE_PROBE, owner)
    assert done.returncode == 0, done.stderr[-2000:]
    assert "flushed" in done.stdout, done.stderr[-2000:]


# --- the legacy viewer ----------------------------------------------------------------------------------------

class _FakePlayer:
    def __init__(self):
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def test_a_ticked_audio_box_plays_with_the_advanced_section_collapsed(monkeypatch):
    monkeypatch.setattr(viewer_panel, "is_audio_backend_available", lambda: True)
    monkeypatch.setattr(viewer_panel, "AudioPlayer", _FakePlayer)
    panel = viewer_panel._ViewerPanel()
    panel._enable_audio.setChecked(True)
    panel._start_audio_player_if_requested()
    assert panel._audio_player is not None
    assert panel._audio_player.started


def test_a_reconnect_stops_the_previous_player():
    panel = viewer_panel._ViewerPanel()
    previous = panel._audio_player = _FakePlayer()
    panel._start_audio_player_if_requested()
    assert previous.stopped


def test_the_viewer_port_opens_unset():
    assert viewer_panel._ViewerPanel()._port.value() == 0


def test_a_session_error_closes_the_window_and_the_player(qapp):
    panel = viewer_panel._ViewerPanel()
    panel._connected = True
    panel._ensure_screen_window()
    player = panel._audio_player = _FakePlayer()
    panel._on_error_main("connection reset")
    assert panel._screen_window is None
    assert player.stopped
    assert qapp.warnings == ["connection reset"]


# --- the host panel ---------------------------------------------------------------------------------------------

class _FakeHost:
    is_running, port, connected_clients, host_id = True, 4321, 0, "123456789"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def start(self):
        return None

    def latest_frame(self):
        raise AssertionError("the hidden preview read a frame")


def _started_panel(monkeypatch):
    monkeypatch.setattr(host_panel, "is_audio_backend_available", lambda: True)
    monkeypatch.setattr(host_panel, "RemoteDesktopHost", _FakeHost)
    panel = host_panel._HostPanel()
    panel._token.setText("tok-at-start")
    panel._enable_audio.setChecked(True)
    panel._start()
    assert settle_op(panel._host_op)
    return panel


def test_the_host_captures_audio_with_the_advanced_section_collapsed(monkeypatch):
    _started_panel(monkeypatch)
    assert registry.host.kwargs["audio_config"].enabled is True


def test_the_share_text_quotes_the_running_host_not_the_edited_fields(monkeypatch):
    panel = _started_panel(monkeypatch)
    panel._token.setText("edited-later")
    panel._transport.setCurrentText("WebSocket")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    panel._copy_share_text()
    text = QApplication.clipboard().text()
    assert "tok-at-start" in text
    assert "edited-later" not in text
    assert "Transport: TCP" in text


def test_the_hidden_preview_reads_no_frames(monkeypatch):
    panel = _started_panel(monkeypatch)
    assert not panel.isVisible()
    panel._refresh_preview()


# --- stored and remote data -----------------------------------------------------------------------------------

def test_address_book_dates_before_1970_and_naive_ones_sort():
    from je_auto_control.gui.remote_desktop.webrtc_dialogs import AddressBookList
    entries = [{"host_id": "a", "last_used": "1969-12-31T00:00:00"},
               {"host_id": "b", "last_used": "0001-01-01T00:00:00+00:00"},
               {"host_id": "c", "last_used": "2026-01-01T00:00:00+00:00"}]
    book = AddressBookList()
    book.populate(entries)
    assert book.count() == 3
    assert book.item(0).text().startswith("(unnamed) - c")


def test_a_naive_last_seen_is_compared_as_utc():
    from je_auto_control.gui.remote_desktop.webrtc_known_hosts import KnownHostsDialog
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert KnownHostsDialog._is_stale("2020-01-01T00:00:00", now=now, stale_after=timedelta(days=90))


def test_remote_file_rows_survive_entries_of_the_wrong_shape():
    from je_auto_control.gui.remote_desktop.webrtc_dialogs import RemoteFilesTable
    table = RemoteFilesTable()
    table.populate([{"name": "a", "size": "big"}, "junk", {"name": "b", "size": float("inf")}], str)
    assert table.rowCount() == 2
    assert [table.item(row, 1).text() for row in range(2)] == ["big", "inf"]


# --- tokens are masked like Quick Connect's ---------------------------------------------------------------------

@pytest.mark.parametrize("build, field", [
    (lambda: host_panel._HostPanel(), "_token"),
    (lambda: viewer_panel._ViewerPanel(), "_token"),
    (lambda: connection_screen.QuickConnectScreen(), "_host_token"),
    (lambda: connection_screen.QuickConnectScreen(), "_connect_token"),
], ids=["host", "viewer", "quick-host", "quick-viewer"])
def test_remote_desktop_tokens_are_masked_with_reveal_and_copy(monkeypatch, build, field):
    from headless._masked_secret import assert_masked_secret
    panel = build()
    try:
        assert_masked_secret(getattr(panel, field), monkeypatch)
    finally:
        panel.dispose()
        panel.deleteLater()


def test_short_fingerprints_accept_any_stored_value():
    from je_auto_control.gui.remote_desktop._helpers import _format_last_seen, _short_fp
    assert _short_fp(12345) == "12345"
    # Windows cannot convert year 1 to local time; other platforms can.
    assert isinstance(_format_last_seen("0001-01-01T00:00:00+00:00"), str)


class _KnownHosts:
    def __init__(self, entries):
        self.entries = dict(entries)

    def list_entries(self):
        return dict(self.entries)

    def forget(self, host_id):
        self.entries.pop(host_id, None)


def test_forget_stale_takes_every_row_the_table_shows_as_stale(monkeypatch):
    from je_auto_control.gui.remote_desktop import webrtc_known_hosts as module
    old = datetime.now(timezone.utc) - timedelta(days=200)
    known = _KnownHosts({"aware": {"last_seen": old.isoformat()},
                         "naive": {"last_seen": old.replace(tzinfo=None).isoformat()},
                         "fresh": {"last_seen": datetime.now(timezone.utc).isoformat()}})
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    dialog = module.KnownHostsDialog(known)
    dialog._on_forget_stale()
    assert sorted(known.entries) == ["fresh"]
    dialog.deleteLater()


@pytest.mark.parametrize("content", [b"\xff\xfe\x00\x01", b"[" * 100_000], ids=["not-utf8", "too-deep"])
def test_a_known_hosts_file_that_cannot_be_read_is_reported(qapp, monkeypatch, tmp_path, content):
    from je_auto_control.gui.remote_desktop import webrtc_known_hosts as module
    path = tmp_path / "known.json"
    path.write_bytes(content)
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *_args: (str(path), ""))
    dialog = module.KnownHostsDialog(_KnownHosts({}))
    dialog._on_import()
    assert len(qapp.warnings) == 1
    dialog.deleteLater()


def test_remote_file_names_cannot_be_edited_under_pull_and_delete():
    from PySide6.QtWidgets import QAbstractItemView
    from je_auto_control.gui.remote_desktop.webrtc_dialogs import RemoteFilesTable
    table = RemoteFilesTable()
    assert table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    table.deleteLater()


_MARKUP = '<img src="file://host/share/x.png"><b>click here</b>'


@pytest.mark.parametrize("panel_class, slot", [
    (viewer_panel._ViewerPanel, "_on_error_main"), (connection_screen.QuickConnectScreen, "_on_error")])
def test_an_error_the_remote_side_worded_is_shown_not_rendered(qapp, panel_class, slot):
    panel = panel_class()
    getattr(panel, slot)(_MARKUP)
    assert len(qapp.warnings) == 1 and "<img" not in qapp.warnings[0]
    panel.dispose()
    panel.deleteLater()
