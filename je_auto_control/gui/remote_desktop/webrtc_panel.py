"""WebRTC sub-tabs for the Remote Desktop tab.

Two sections per panel:
  * Signaling server flow — the AnyDesk-style "type host ID and connect"
    UX, backed by ``signaling_server.py``. Recommended for daily use.
  * Manual SDP exchange — copy/paste fallback when no server is reachable.

An advanced collapsible group below exposes STUN/TURN servers; defaults
to Google's public STUN, which is enough for most LAN/home-network
scenarios. Mobile / strict-NAT users will want to add a TURN server.

The two panel classes own the state, the signal wiring and the handful of slots
other code patches by name here; each interaction group lives in a mixin module:
``webrtc_host_{ui,connection,sessions,media,trust}`` and
``webrtc_viewer_{ui,connection,media,files,address_book}``. Signals, defaults
and the config reader they share are in ``webrtc_panel_common``.
"""
from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractButton, QMessageBox, QWidget,
)

from je_auto_control.gui.remote_desktop._webrtc_types import MultiViewerHostT, SessionRecorderT, WebRTCDesktopViewerT
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._slow_op import StopQueue
from je_auto_control.gui.remote_desktop.view_lifetime import ViewLifetime
from je_auto_control.gui.remote_desktop._helpers import (
    _t,
)
from je_auto_control.gui.remote_desktop.blanking_overlay import BlankingOverlay
from je_auto_control.gui.remote_desktop.remote_screen_window import (
    RemoteScreenWindow,
)
from je_auto_control.gui.remote_desktop.annotation_overlay import (
    HostAnnotationOverlay,
)
from je_auto_control.gui.remote_desktop.tray_icon import install_host_tray
from je_auto_control.gui.remote_desktop.viewer_screen_window import (
    ViewerScreenWindow,
)
from je_auto_control.gui.remote_desktop.webrtc_dialogs import (
    PendingViewerDialog,
)
from je_auto_control.gui.remote_desktop.webrtc_workers import (
    HostPublishLoopWorker, ViewerAnswerPushWorker, ViewerSignalingWorker,
)
from je_auto_control.gui.tab_task_controller import CancellationToken, TaskHandle, task_controller
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.remote_desktop import (
    default_address_book,
    default_trust_list, is_webrtc_available,
    load_or_create_viewer_id,
)
from je_auto_control.utils.remote_desktop.adaptive_bitrate import (
    AdaptiveBitrateController,
)
from je_auto_control.utils.remote_desktop.session_quality_cache import (
    SessionQualityCache,
)
from je_auto_control.utils.remote_desktop.webrtc_stats import (
    StatsPoller,
)
from je_auto_control.gui.remote_desktop.webrtc_panel_common import (
    _PanelSignals,
)
from je_auto_control.gui.remote_desktop.webrtc_host_ui import _HostUiMixin
from je_auto_control.gui.remote_desktop.webrtc_host_trust import _HostTrustMixin
from je_auto_control.gui.remote_desktop.webrtc_host_media import _HostMediaMixin
from je_auto_control.gui.remote_desktop.webrtc_host_sessions import _HostSessionsMixin
from je_auto_control.gui.remote_desktop.webrtc_host_connection import _HostConnectionMixin
from je_auto_control.gui.remote_desktop.webrtc_viewer_ui import _ViewerUiMixin
from je_auto_control.gui.remote_desktop.webrtc_viewer_files import _ViewerFilesMixin
from je_auto_control.gui.remote_desktop.webrtc_viewer_address_book import _ViewerAddressBookMixin
from je_auto_control.gui.remote_desktop.webrtc_viewer_media import _ViewerMediaMixin
from je_auto_control.gui.remote_desktop.webrtc_viewer_connection import _ViewerConnectionMixin

if TYPE_CHECKING:  # imported lazily at runtime to keep startup cheap
    from je_auto_control.gui.remote_desktop.frame_display import _FrameDisplay
    from je_auto_control.utils.remote_desktop.file_sync import (
        FolderSyncEngine,
    )
    from je_auto_control.utils.remote_desktop.lan_discovery import (
        HostAdvertiser,
    )


def _turned_off(button: QAbstractButton) -> bool:
    """Whether ``button`` itself was disabled; ``isEnabled()`` is also false inside a collapsed section."""
    return button.testAttribute(Qt.WidgetAttribute.WA_ForceDisabled)


class _WebRTCHostPanel(_HostUiMixin, _HostTrustMixin, _HostMediaMixin, _HostSessionsMixin,
                       _HostConnectionMixin):
    """Host: stream this machine's screen and accept viewer input."""

    #: Checked against the active RBAC role when the page is shown.
    REQUIRED_COMMANDS = ("AC_start_webrtc_host", "AC_stop_webrtc_host")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._view = ViewLifetime(self)
        self._multi_host: Optional[MultiViewerHostT] = None
        self._publish_loop: Optional[HostPublishLoopWorker] = None
        self._manual_session_id: Optional[str] = None
        self._answer_task: Optional[TaskHandle] = None     # the answer being applied, off-thread
        self._file_task: Optional[TaskHandle] = None       # the file push in progress, off-thread
        self._trust_task: Optional[TaskHandle] = None      # a trust-list write, import or export, off-thread
        self._admissions = 0                # accept-and-trust answers still recording the viewer, off-thread
        self._stops = StopQueue(self)
        self._stops.drained.connect(self._on_stops_drained)
        self._stopping_sessions: set[str] = set()
        self._adaptive_controller: Optional[AdaptiveBitrateController] = None
        self._adaptive_poller: Optional[StatsPoller] = None
        self._session_pollers: dict[str, StatsPoller] = {}    # session_id -> StatsPoller
        # Lock-protected cache replacing two raw dicts; mutated by the
        # asyncio bridge thread (StatsPoller cb) and read/cleared by the
        # Qt thread. See utils/remote_desktop/session_quality_cache.py.
        self._session_cache = SessionQualityCache()
        self._trust_list = default_trust_list()
        self._blanking: Optional[BlankingOverlay] = None
        self._viewer_screen_window: Optional[ViewerScreenWindow] = None
        self._lan_advertiser: Optional["HostAdvertiser"] = None
        self._annotation_overlay: Optional[HostAnnotationOverlay] = None
        self._tray = install_host_tray(
            on_open=self._on_tray_open,
            on_stop=self._on_tray_stop,
            on_quit=self._on_tray_quit,
            parent=self,
        )
        self._signals = _PanelSignals()
        self._signals.state.connect(self._view.callback("_on_state"))
        self._signals.auth.connect(self._view.callback("_on_auth"))
        self._signals.pending_viewer.connect(self._view.callback("_on_pending_viewer"))
        self._signals.session_count.connect(self._view.callback("_on_session_count"))
        self._signals.viewer_video_frame.connect(self._view.callback("_on_viewer_video_image"))
        self._signals.annotation.connect(self._view.callback("_on_annotation_event"))
        self._signals.stats.connect(self._view.callback("_update_host_quality_dot"))
        self._build_ui()
        self._refresh_trusted_list()
        self._update_availability()

    def _update_availability(self) -> None:
        if not is_webrtc_available():
            for widget in (self._generate_btn, self._apply_btn,
                           self._publish_btn):
                widget.setEnabled(False)
            self._status.show("rd_webrtc_unavailable")

    def prefill(self, token: Optional[str] = None,
                host_id: Optional[str] = None,
                signaling_url: Optional[str] = None) -> None:
        """Hand-off entry point used by the Quick Connect screen.

        Populates the signaling-flow fields so the operator can click
        "Publish and wait for viewer" without retyping a token they
        already shared on the Quick Connect tab.
        """
        if token:
            self._token_edit.setText(token)
        if host_id:
            self._host_id_edit.setText(host_id)
        if signaling_url and hasattr(self, "_server_edit"):
            self._server_edit.setText(signaling_url)

    def dispose(self) -> None:
        """Release what the panel holds beyond its widgets -- including the host it runs.

        Called through ``RemoteDesktopTab.dispose()``; safe to call twice.
        The TCP panels leave their host in the registry, where scripts and
        the other panels still reach it. A WebRTC host belongs to this panel
        alone: with the panel gone nothing could stop it, and it would go on
        sharing the screen unseen. So it is stopped here, in the background as
        for Stop, together with the signaling loop, the LAN advertiser, the
        offer or file push still out and the tray icon.
        """
        self._view.retire()
        release_resources(self, self._stop_host_if_any, self._hide_blanking, self._hide_tray)

    def _hide_blanking(self) -> None:
        # Its windows have no parent: left up, nothing on screen could take them down.
        self._on_toggle_blanking(False)

    def _hide_tray(self) -> None:
        if self._tray is not None:
            self._tray.hide()

    def _on_tray_open(self) -> None:
        # Not self.window(): for a few event-loop turns after a theme switch
        # this page is parked outside the main window's tree.
        win = self.window()
        win.showNormal()
        win.raise_()
        win.activateWindow()

    def _on_tray_stop(self) -> None:
        self._stop_host_if_any()
        self._signals.session_count.emit(0)

    def _on_tray_quit(self) -> None:
        self._stop_host_if_any()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    def _on_pending_viewer(self, session_id: str, viewer_id: object) -> None:
        if self._multi_host is None:
            return
        dialog = PendingViewerDialog(viewer_id if isinstance(viewer_id, str) else None,
                                     parent=self)
        dialog.exec()
        choice = dialog.choice()
        # The host can stop while the dialog is open (Stop, the tray): the
        # answer then raised AttributeError on a host that was gone.
        host = self._multi_host
        if host is None:
            return
        if choice == PendingViewerDialog.AcceptAndTrust:
            self._admit_and_trust(host, session_id)
            return
        try:
            if choice == PendingViewerDialog.AcceptOnce:
                host.approve_pending_viewer(session_id)
            else:
                host.reject_pending_viewer(session_id)
        except KeyError:
            # Session may have been torn down between prompt and decision.
            return
        self._signals.session_count.emit(host.session_count())

    def _admit_and_trust(self, host: MultiViewerHostT, session_id: str) -> None:
        """Answer "accept and trust" on a worker: recording the viewer writes the trust-list file.

        The whole ``trust_pending_viewer`` call goes there unsplit, so the
        viewer is admitted by that call alone, after its write, exactly as
        when it ran here. The trusted list is disabled until it returns.
        """
        self._admissions += 1
        self._trusted_list.setEnabled(False)
        task = task_controller().submit(functools.partial(_trust_and_admit, host, session_id), owner=self)
        task.result.connect(self._on_viewer_admitted)
        task.error.connect(self._on_admission_failed)
        task.finished.connect(self._on_admission_done)

    def _on_viewer_admitted(self, _outcome: object = None) -> None:
        host = self._multi_host
        if host is not None:                # stopped while the trust was being recorded
            self._signals.session_count.emit(host.session_count())

    def _on_admission_failed(self, error: object) -> None:
        # KeyError: the session was torn down between the prompt and the answer.
        if not isinstance(error, KeyError):
            autocontrol_logger.warning("accept and trust viewer: %r", error)

    def _on_admission_done(self) -> None:
        self._admissions = max(0, self._admissions - 1)
        if self._admissions == 0:
            self._trusted_list.setEnabled(True)
        self._refresh_trusted_list()

    def _set_hosting(self, hosting: bool) -> None:
        if self._tray is not None:
            self._tray.set_hosting(hosting)

    def _on_state(self, state: str) -> None:
        self._status.show_rendered(lambda: f"{_t('rd_webrtc_state_label')} {state}")

    def _on_auth(self, ok: bool) -> None:
        key = "rd_webrtc_auth_ok" if ok else "rd_webrtc_auth_fail"
        self._status.show(key)

    def _show_error(self, error: Exception) -> None:
        autocontrol_logger.warning("webrtc host panel error: %r", error)
        QMessageBox.warning(self, "WebRTC", str(error))

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        self._apply_session_headers()
        self._status.retranslate()
        self._host_quality_tip.retranslate()
        if self._tray is not None:
            self._tray.retranslate()
        if self._viewer_screen_window is not None:
            self._viewer_screen_window.retranslate()
        host = self._multi_host
        self._sessions_label.setText(
            _t("rd_webrtc_sessions_count").format(n=host.session_count() if host is not None else 0))
        self._hw_codec_combo.setItemText(0, _t("rd_webrtc_hw_codec_off"))
        if self._monitor_combo.itemText(0) != "#0":     # "#0": the monitors could not be listed
            self._monitor_combo.setItemText(0, _t("rd_webrtc_monitor_all"))


class _WebRTCViewerPanel(_ViewerUiMixin, _ViewerFilesMixin, _ViewerAddressBookMixin, _ViewerMediaMixin,
                         _ViewerConnectionMixin):
    """Viewer: receive screen and send input."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._view = ViewLifetime(self)
        self._viewer: Optional[WebRTCDesktopViewerT] = None
        self._file_task: Optional[TaskHandle] = None       # the upload in progress, off-thread
        self._book_task: Optional[TaskHandle] = None       # an address-book write, import or export, off-thread
        self._offer_worker: Optional[ViewerSignalingWorker] = None
        self._answer_worker: Optional[ViewerAnswerPushWorker] = None
        self._stops = StopQueue(self)
        self._stops.drained.connect(self._on_stops_drained)
        self._address_book = default_address_book()
        from je_auto_control.utils.remote_desktop import default_known_hosts
        self._known_hosts = default_known_hosts()
        try:
            self._viewer_id: Optional[str] = load_or_create_viewer_id()
        except OSError as error:
            autocontrol_logger.warning("viewer_id init: %r", error)
            self._viewer_id = None
        self._recorder: Optional[SessionRecorderT] = None
        self._stats_poller: Optional[StatsPoller] = None
        self._sync_engine: Optional["FolderSyncEngine"] = None
        self._auto_reconnect_attempts = 0
        self._viewer_episode: object = None
        self._reconnect_counted_for: object = None
        self._user_initiated_disconnect = False
        # One timer, so Stop can cancel a reconnect that is waiting out its
        # back-off: a singleShot could not be, and reconnected after Stop.
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._on_connect_via_server)
        # AnyDesk-style pop-out: created on auth_ok, hidden on stop.
        # Set by _ensure_screen_window().
        self._screen_window: Optional[RemoteScreenWindow] = None
        self._signals = _PanelSignals()
        self._signals.frame.connect(self._view.callback("_on_frame_image"))
        self._signals.state.connect(self._view.callback("_on_state"))
        self._signals.auth.connect(self._view.callback("_on_auth"))
        self._signals.stats.connect(self._view.callback("_on_stats"))
        self._signals.inbox_listing.connect(self._view.callback("_on_inbox_listing"))
        self._signals.inbox_op.connect(self._view.callback("_on_inbox_op_result"))
        self._signals.file_received.connect(self._view.callback("_on_file_received_ui"))
        self._build_ui()
        self._refresh_address_book()
        self._update_availability()

    def prefill(self, host_id: Optional[str] = None,
                token: Optional[str] = None,
                signaling_url: Optional[str] = None) -> None:
        """Hand-off entry point used by the Quick Connect screen.

        Populates the signaling-flow fields without auto-clicking
        Connect so the operator can sanity-check before the session
        starts. Empty strings are ignored so callers can fill only the
        fields they actually know.
        """
        if host_id:
            self._host_id_edit.setText(host_id)
        if token:
            self._token_edit.setText(token)
        if signaling_url:
            self._server_edit.setText(signaling_url)

    def _wire_input_signals(self) -> None:
        # Wire the hidden inline _FrameDisplay too, even though it
        # never gets focus while the popup is open — leaves the slots
        # in place if the panel ever reverts to inline display in the
        # future.
        self._wire_display_input(self._frame_display)

    def _wire_display_input(self, source: _FrameDisplay | RemoteScreenWindow) -> None:
        """Wire mouse / keyboard / annotation signals from ``source``.

        ``source`` can be a :class:`_FrameDisplay` or a
        :class:`RemoteScreenWindow` — both expose the same Signal
        names with matching shapes.
        """
        source.mouse_moved.connect(
            lambda x, y: self._send({"type": "mouse_move",
                                     "x": int(x), "y": int(y)}))
        source.mouse_pressed.connect(
            lambda x, y, b: self._send({"type": "mouse_press",
                                        "x": int(x), "y": int(y),
                                        "button": b}))
        source.mouse_released.connect(
            lambda x, y, b: self._send({"type": "mouse_release",
                                        "x": int(x), "y": int(y),
                                        "button": b}))
        source.mouse_scrolled.connect(
            lambda x, y, a: self._send({"type": "mouse_scroll",
                                        "x": int(x), "y": int(y),
                                        "amount": int(a)}))
        source.key_pressed.connect(
            lambda k: self._send({"type": "key_press", "keycode": k}))
        source.key_released.connect(
            lambda k: self._send({"type": "key_release", "keycode": k}))
        source.type_text.connect(
            lambda text: self._send({"type": "type_text", "text": text}))
        source.annotation_event.connect(self._on_annotation_segment)

    def _update_availability(self) -> None:
        if not is_webrtc_available():
            for widget in (self._answer_btn, self._connect_btn):
                widget.setEnabled(False)
            self._status.show("rd_webrtc_unavailable")

    def dispose(self) -> None:
        """Release what the panel holds beyond its widgets -- including the session it is in.

        Called through ``RemoteDesktopTab.dispose()``; safe to call twice.
        The TCP panels leave their session in the registry, where scripts and
        the other panels still reach it. A WebRTC session belongs to this
        panel alone, so it is ended here, in the background as for Stop:
        the pending reconnect, the signaling workers, the recording, the
        folder sync, the upload still out and the pop-out window go with it.
        """
        self._view.retire()
        release_resources(self, self._end_session_for_good)

    def _end_session_for_good(self) -> None:
        self._user_initiated_disconnect = True      # a late "disconnected" must not schedule a reconnect
        self._stop_viewer_if_any()
        self._close_screen_window()

    def _ensure_screen_window(self) -> RemoteScreenWindow:
        if self._screen_window is not None:
            return self._screen_window
        host_id = self._host_id_edit.text().strip()
        title = (
            _t("rd_remote_screen_title_with_id").replace("{host_id}", host_id)
            if host_id else _t("rd_remote_screen_title")
        )
        window = RemoteScreenWindow(title, parent=self)
        # Wire the popup's input signals so mouse/keyboard inside the
        # popup feed the WebRTC control channel just like the hidden
        # inline display would.
        self._wire_display_input(window)
        # With the pen already on, a new window drew nothing: every stroke
        # reached the host as real clicks and drags.
        window.set_pen_mode(self._pen_btn.isChecked())
        window.closed.connect(self._on_screen_window_closed)
        self._screen_window = window
        return window

    def _close_screen_window(self) -> None:
        window = self._screen_window
        self._screen_window = None
        if window is not None:
            try:
                window.closed.disconnect(self._on_screen_window_closed)
            except (RuntimeError, TypeError):
                pass
            window.hide()
            window.deleteLater()

    def _on_screen_window_closed(self) -> None:
        # Operator dismissed the popup → fall through to disconnect.
        if self._viewer is not None:
            self._on_stop()

    def _on_state(self, state: str) -> None:
        self._status.show_rendered(lambda: f"{_t('rd_webrtc_state_label')} {state}")
        if state in ("failed", "disconnected"):
            self._maybe_schedule_auto_reconnect()

    def _send(self, payload: dict[str, Any]) -> None:
        if self._viewer is None or not self._viewer.authenticated:
            return
        try:
            self._viewer.send_input(payload)
        except (RuntimeError, OSError) as error:
            logging.getLogger(__name__).debug("send_input: %r", error)

    def _show_error(self, error: Exception) -> None:
        autocontrol_logger.warning("webrtc viewer panel error: %r", error)
        QMessageBox.warning(self, "WebRTC", str(error))

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        for text in (self._status, self._quality_tip, self._stats_text):
            text.retranslate()
        self._remote_files_table.retranslate()
        self._tag_filter_combo.setItemText(0, _t("rd_webrtc_tag_all"))
        for index in range(self._bandwidth_combo.count()):
            self._bandwidth_combo.setItemText(index, _t(f"rd_webrtc_bandwidth_{self._bandwidth_combo.itemData(index)}"))
        # The registered texts are the buttons' idle ones.
        # A button turned off while its stop runs, not one inside a collapsed (so disabled) section.
        if self._recorder is not None or _turned_off(self._record_btn):
            self._record_btn.setText(_t("rd_webrtc_stop_recording" if self._recorder is not None
                                        else "gui_op_stopping"))
        if self._sync_engine is not None or _turned_off(self._sync_btn):
            self._sync_btn.setText(_t("rd_webrtc_sync_stop" if self._sync_engine is not None else "gui_op_stopping"))
        self._pen_btn.setText(_t("rd_webrtc_pen_on" if self._pen_btn.isChecked() else "rd_webrtc_pen_off"))


def _trust_and_admit(host: MultiViewerHostT, session_id: str, _token: CancellationToken) -> None:
    """Worker thread: record the pending viewer as trusted and admit it (one backend call)."""
    host.trust_pending_viewer(session_id)


__all__ = ["_PanelSignals", "_WebRTCHostPanel", "_WebRTCViewerPanel"]
