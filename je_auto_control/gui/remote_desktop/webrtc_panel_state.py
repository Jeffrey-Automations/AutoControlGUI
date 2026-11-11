"""Typed state and slot contracts of the composed WebRTC host and viewer widgets."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional, Sequence

from je_auto_control.gui.remote_desktop.webrtc_panel_common import _PanelPart

if TYPE_CHECKING:
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtWidgets import (
        QCheckBox, QComboBox, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget, QTextEdit,
    )
    from je_auto_control.gui.remote_desktop._webrtc_types import AvFrameT, MultiViewerHostT, WebRTCDesktopViewerT
    from je_auto_control.gui.remote_desktop.annotation_overlay import HostAnnotationOverlay
    from je_auto_control.gui.remote_desktop.viewer_screen_window import ViewerScreenWindow
    from je_auto_control.gui.remote_desktop.remote_screen_window import RemoteScreenWindow
    from je_auto_control.gui.remote_desktop.tray_icon import HostTrayIcon
    from je_auto_control.gui.remote_desktop.frame_display import _FrameDisplay
    from je_auto_control.gui.remote_desktop.sparkline import Sparkline
    from je_auto_control.gui.remote_desktop.webrtc_dialogs import AddressBookList, RemoteFilesTable, TrustedViewersList
    from je_auto_control.utils.remote_desktop.session_quality_cache import SessionQualityCache
    from je_auto_control.utils.remote_desktop.webrtc_stats import StatsPoller
    from je_auto_control.utils.remote_desktop.trust_list import TrustList
    from je_auto_control.utils.remote_desktop.address_book import AddressBook
    from je_auto_control.utils.remote_desktop.fingerprint import KnownHosts


class _HostPanelPart(_PanelPart):
    """State initialized by the host panel and slots supplied by its mixins."""

    _accept_viewer_video_check: QCheckBox
    _adaptive_check: QCheckBox
    _annotation_overlay: Optional[HostAnnotationOverlay]
    _answer_input: QTextEdit
    _fps_spin: QSpinBox
    _host_quality_dot: QLabel
    _hw_codec_combo: QComboBox
    _ip_whitelist_edit: QTextEdit
    _max_bitrate_spin: QSpinBox
    _maybe_start_adaptive: Callable[[], None]
    _monitor_combo: QComboBox
    _multi_host: Optional[MultiViewerHostT]
    _offer_view: QTextEdit
    _on_apply_answer: Callable[[], None]
    _on_clear_trust: Callable[[], None]
    _on_disconnect_selected: Callable[[], None]
    _on_export_trust: Callable[[], None]
    _on_generate_offer: Callable[[], None]
    _on_hw_codec_changed: Callable[[], None]
    _on_import_trust: Callable[[], None]
    _on_monitor_changed: Callable[[int], None]
    _on_pick_region: Callable[[], None]
    _on_publish_via_server: Callable[[], None]
    _on_push_file: Callable[[], None]
    _on_regen_id: Callable[[], None]
    _on_remove_trust: Callable[[str], None]
    _on_remove_trust_button: Callable[[], None]
    _on_session_authed: Callable[[str], None]
    _on_sessions_context_menu: Callable[[QPoint], None]
    _on_stop: Callable[[], None]
    _on_toggle_accept_opus_audio: Callable[[bool], None]
    _on_toggle_accept_viewer_video: Callable[[bool], None]
    _on_toggle_adaptive: Callable[[bool], None]
    _on_toggle_blanking: Callable[[bool], None]
    _on_toggle_mic_receive: Callable[[bool], None]
    _on_toggle_readonly: Callable[[bool], None]
    _on_view_audit: Callable[[], None]
    _populate_monitor_combo: Callable[[], None]
    _readonly_check: QCheckBox
    _region_edit: QLineEdit
    _require_multi_host: Callable[[], MultiViewerHostT]
    _reset_host_quality_dot: Callable[[], None]
    _session_cache: SessionQualityCache
    _session_pollers: dict[str, StatsPoller]
    _sessions_label: QLabel
    _sessions_table: QTableWidget
    _set_hosting: Callable[[bool], None]
    _show_error: Callable[[Exception], None]
    _stop_adaptive: Callable[[], None]
    _stopping_sessions: set[str]
    _tray: Optional[HostTrayIcon]
    _trust_list: TrustList
    _trust_session_viewer: Callable[[str], None]
    _trusted_list: TrustedViewersList
    _viewer_screen_window: Optional[ViewerScreenWindow]


class _ViewerPanelPart(_PanelPart):
    """State initialized by the viewer panel and slots supplied by its mixins."""

    _address_book: AddressBook
    _address_list: AddressBookList
    _answer_view: QTextEdit
    _auto_reconnect_check: QCheckBox
    _bandwidth_combo: QComboBox
    _bitrate_spark: Sparkline
    _close_screen_window: Callable[[], None]
    _ensure_screen_window: Callable[[], RemoteScreenWindow]
    _frame_display: _FrameDisplay
    _known_hosts: KnownHosts
    _mic_btn: QPushButton
    _offer_input: QTextEdit
    _on_ab_clear: Callable[[], None]
    _on_ab_export: Callable[[], None]
    _on_ab_import: Callable[[], None]
    _on_address_chosen: Callable[[dict[str, object]], None]
    _on_address_favorite: Callable[[dict[str, object]], None]
    _on_address_removed: Callable[[dict[str, object]], None]
    _on_address_tags: Callable[[dict[str, object]], None]
    _on_av_frame: Callable[[AvFrameT], None]
    _on_browse_delete_button: Callable[[], None]
    _on_browse_pull_button: Callable[[], None]
    _on_browse_refresh: Callable[[], None]
    _on_connect_selected_address: Callable[[], None]
    _on_connect_via_server: Callable[[], None]
    _on_copy_name: Callable[[str], None]
    _on_create_answer: Callable[[], None]
    _on_delete_names: Callable[[Sequence[str]], None]
    _on_lan_browse: Callable[[], None]
    _on_manage_known_hosts: Callable[[], None]
    _on_pen_clear: Callable[[], None]
    _on_pull_names: Callable[[Sequence[str]], None]
    _on_received_file: Callable[[object], None]
    _on_remove_selected_address: Callable[[], None]
    _on_save_current_address: Callable[[], None]
    _on_send_cad: Callable[[], None]
    _on_send_file: Callable[[], None]
    _on_stop: Callable[[], None]
    _on_sync_browse: Callable[[], None]
    _on_toggle_mic: Callable[[bool], None]
    _on_toggle_pen: Callable[[bool], None]
    _on_toggle_recording: Callable[[bool], None]
    _on_toggle_share_my_screen: Callable[[bool], None]
    _on_toggle_share_opus_mic: Callable[[bool], None]
    _on_toggle_sync: Callable[[bool], None]
    _on_upload_paths: Callable[[Sequence[str]], None]
    _on_wake_on_lan: Callable[[], None]
    _pen_btn: QPushButton
    _quality_dot: QLabel
    _reconnect_delay_spin: QSpinBox
    _reconnect_max_spin: QSpinBox
    _reconnect_timer: QTimer
    _record_btn: QPushButton
    _refresh_address_book: Callable[[], None]
    _remote_files_table: RemoteFilesTable
    _screen_window: Optional[RemoteScreenWindow]
    _show_error: Callable[[Exception], None]
    _start_stats_polling: Callable[[], None]
    _stats_label: QLabel
    _stop_stats_polling: Callable[[], None]
    _sync_btn: QPushButton
    _sync_dir_edit: QLineEdit
    _tag_filter_combo: QComboBox
    _viewer: Optional[WebRTCDesktopViewerT]
    _viewer_id: Optional[str]
    _wire_input_signals: Callable[[], None]
