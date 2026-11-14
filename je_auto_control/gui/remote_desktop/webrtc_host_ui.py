"""Widget construction for the WebRTC host panel.

One interaction group of ``webrtc_panel._WebRTCHostPanel``, kept as a mixin so the panel class
still owns every widget and slot under its original name.
"""
from __future__ import annotations

from je_auto_control.gui.remote_desktop.webrtc_panel_state import _HostPanelPart


from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QSpinBox, QTableWidget, QTextEdit, QVBoxLayout, QWidget,
)

from je_auto_control.gui.adaptive.flow_layout import flow_of
from je_auto_control.gui.adaptive.responsive import ResponsiveBox
from je_auto_control.gui.adaptive.surfaces import Card, set_role

from je_auto_control.gui.remote_desktop._helpers import (
    _pane, _row, _t,
)
from je_auto_control.gui.remote_desktop.advanced_group import (
    build_advanced_group,
)
from je_auto_control.gui.remote_desktop.trusted_group import (
    build_trusted_group,
)
from je_auto_control.gui.remote_desktop.webrtc_workers import (
    generate_host_id,
)
from je_auto_control.gui.remote_desktop.webrtc_panel_common import (
    _DEFAULT_FPS, _DEFAULT_SIGNALING_URL, _QUALITY_DOT_STYLE,
)


class _HostUiMixin(_HostPanelPart):
    """Methods of ``_WebRTCHostPanel``; the module docstring says which group."""

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(self._build_signaling_group())
        layout.addWidget(self._build_config_group())
        layout.addWidget(self._build_manual_group())
        layout.addWidget(build_advanced_group(self, hardware_codec=self))
        layout.addWidget(build_trusted_group(self))
        layout.addWidget(self._build_sessions_card(), stretch=1)

    def _build_sessions_card(self) -> Card:
        """Status line, the live sessions table and what can be done to a session."""
        card = Card()
        self._status_label = QLabel(_t("rd_webrtc_status_idle"))
        self._status_label.setWordWrap(True)
        set_role(self._status_label, "hint")
        card.add(self._status_label)
        sessions_row = QHBoxLayout()
        self._host_quality_dot = QLabel()
        self._host_quality_dot.setFixedSize(14, 14)
        self._host_quality_dot.setStyleSheet(
            _QUALITY_DOT_STYLE,
        )
        self._host_quality_dot.setToolTip(_t("rd_webrtc_quality_unknown"))
        sessions_row.addWidget(self._host_quality_dot)
        self._sessions_label = QLabel(_t("rd_webrtc_sessions_count").format(n=0))
        sessions_row.addWidget(self._sessions_label, stretch=1)
        card.add(sessions_row)
        self._sessions_table = QTableWidget(0, 5)
        self._sessions_table.setHorizontalHeaderLabels([
            "",  # quality dot column
            _t("rd_webrtc_sess_col_id"),
            _t("rd_webrtc_sess_col_viewer"),
            _t("rd_webrtc_sess_col_state"),
            _t("rd_webrtc_sess_col_connected"),
        ])
        self._sessions_table.setColumnWidth(0, 18)
        self._sessions_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch,
        )
        self._sessions_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers,
        )
        # Hint at a comfortable starting height, but let the table
        # grow with the window instead of pinning it at 140 px even
        # when the operator has a 4K monitor's worth of space.
        self._sessions_table.setMinimumHeight(140)
        self._sessions_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows,
        )
        self._sessions_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection,
        )
        self._sessions_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu,
        )
        self._sessions_table.customContextMenuRequested.connect(
            self._on_sessions_context_menu,
        )
        card.add(self._sessions_table, stretch=1)
        self._disconnect_btn = self._tr(
            QPushButton(), "rd_webrtc_disconnect_selected",
        )
        self._disconnect_btn.clicked.connect(self._on_disconnect_selected)
        self._push_file_btn = self._tr(QPushButton(), "rd_webrtc_push_file")
        self._push_file_btn.clicked.connect(self._on_push_file)
        audit_btn = self._tr(QPushButton(), "rd_webrtc_view_audit")
        audit_btn.clicked.connect(self._on_view_audit)
        card.add(flow_of(self._disconnect_btn, self._push_file_btn, audit_btn))
        return card

    def _build_signaling_group(self) -> QGroupBox:
        group = self._tr(QGroupBox(), "rd_webrtc_signaling_group")
        form = QFormLayout()
        self._server_edit = QLineEdit(_DEFAULT_SIGNALING_URL)
        form.addRow(self._tr(QLabel(), "rd_webrtc_server_label"), self._server_edit)
        self._host_id_edit = QLineEdit(generate_host_id())
        regen = self._tr(QPushButton(), "rd_webrtc_regen_id")
        regen.clicked.connect(self._on_regen_id)
        form.addRow(self._tr(QLabel(), "rd_webrtc_host_id_label"), _row(self._host_id_edit, regen))
        self._secret_edit = QLineEdit()
        self._secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(self._tr(QLabel(), "rd_webrtc_secret_label"), self._secret_edit)
        self._publish_btn = self._tr(
            QPushButton(), "rd_webrtc_publish_via_server",
        )
        self._publish_btn.clicked.connect(self._on_publish_via_server)
        form.addRow(self._publish_btn)
        # Read-only fingerprint label + copy button
        from je_auto_control.utils.remote_desktop.fingerprint import (
            fingerprint_for_display, load_or_create_host_fingerprint,
        )
        try:
            fp = load_or_create_host_fingerprint()
        except OSError:
            fp = ""
        self._fingerprint_label = QLabel(
            fingerprint_for_display(fp) if fp else "",
        )
        self._fingerprint_label.setStyleSheet(
            "color: #888; font-family: 'Consolas', monospace; font-size: 10pt;",
        )
        self._fingerprint_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse,
        )
        # One unbreakable run of hex: let it clip on a narrow window rather
        # than widen the page; the tooltip and the Copy button hold all of it.
        self._fingerprint_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._fingerprint_label.setToolTip(self._fingerprint_label.text())
        copy_fp_btn = self._tr(QPushButton(), "rd_webrtc_copy_fingerprint")
        copy_fp_btn.clicked.connect(lambda: self._on_copy_fingerprint(fp))
        form.addRow(self._tr(QLabel(), "rd_webrtc_my_fingerprint"), _row(self._fingerprint_label, copy_fp_btn))
        group.setLayout(form)
        return group

    def _on_copy_fingerprint(self, fp: str) -> None:
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(fp)

    def _build_config_group(self) -> QGroupBox:
        group = self._tr(QGroupBox(), "rd_webrtc_config_group")
        form = QFormLayout()
        self._token_edit = self._tr(QLineEdit(), "rd_token_placeholder")
        form.addRow(self._tr(QLabel(), "rd_token_label"), self._token_edit)
        self._monitor_combo = QComboBox()
        self._populate_monitor_combo()
        self._monitor_combo.currentIndexChanged.connect(
            self._on_monitor_changed,
        )
        form.addRow(self._tr(QLabel(), "rd_webrtc_monitor_label"), self._monitor_combo)
        self._fps_spin = QSpinBox()
        self._fps_spin.setRange(1, 60)
        self._fps_spin.setValue(_DEFAULT_FPS)
        form.addRow(self._tr(QLabel(), "rd_fps_label"), self._fps_spin)
        self._max_bitrate_spin = QSpinBox()
        self._max_bitrate_spin.setRange(0, 50000)
        self._max_bitrate_spin.setSingleStep(500)
        self._max_bitrate_spin.setSuffix(" kbps (0=∞)")
        self._max_bitrate_spin.setValue(0)
        form.addRow(self._tr(QLabel(), "rd_webrtc_max_bitrate"), self._max_bitrate_spin)
        self._region_edit = QLineEdit()
        self._tr(self._region_edit, "rd_webrtc_region_placeholder",
                 "setPlaceholderText")
        pick_region_btn = self._tr(QPushButton(), "rd_webrtc_pick_region")
        pick_region_btn.clicked.connect(self._on_pick_region)
        form.addRow(self._tr(QLabel(), "rd_webrtc_region_label"), _row(self._region_edit, pick_region_btn))
        self._ip_whitelist_edit = QTextEdit()
        self._ip_whitelist_edit.setMaximumHeight(60)
        self._tr(self._ip_whitelist_edit, "rd_webrtc_ip_whitelist_ph",
                 "setPlaceholderText")
        form.addRow(self._tr(QLabel(), "rd_webrtc_ip_whitelist"), self._ip_whitelist_edit)
        fields = QWidget()
        fields.setProperty("role", "bare")
        form.setContentsMargins(0, 0, 0, 0)
        fields.setLayout(form)
        # The fields and the switches sit side by side, and stack when narrow.
        layout = QVBoxLayout()
        layout.addWidget(ResponsiveBox(fields, self._build_config_switches(), stretches=(3, 2)))
        group.setLayout(layout)
        return group

    def _build_config_switches(self) -> QWidget:
        """The on/off options of the config group, one per line."""
        self._cursor_check = self._tr(QCheckBox(), "rd_webrtc_show_cursor")
        self._cursor_check.setChecked(True)
        self._blank_check = self._tr(QCheckBox(), "rd_webrtc_blank_screen")
        self._blank_check.setChecked(False)
        self._blank_check.toggled.connect(self._on_toggle_blanking)
        self._readonly_check = self._tr(QCheckBox(), "rd_webrtc_read_only")
        self._readonly_check.setChecked(False)
        self._readonly_check.toggled.connect(self._on_toggle_readonly)
        self._adaptive_check = self._tr(QCheckBox(), "rd_webrtc_adaptive")
        self._adaptive_check.setChecked(True)
        self._adaptive_check.toggled.connect(self._on_toggle_adaptive)
        self._mic_recv_check = self._tr(QCheckBox(), "rd_webrtc_recv_mic")
        self._mic_recv_check.setChecked(False)
        self._mic_recv_check.toggled.connect(self._on_toggle_mic_receive)
        self._accept_viewer_video_check = self._tr(
            QCheckBox(), "rd_webrtc_accept_viewer_video",
        )
        self._accept_viewer_video_check.setChecked(False)
        self._accept_viewer_video_check.toggled.connect(
            self._on_toggle_accept_viewer_video,
        )
        self._accept_opus_audio_check = self._tr(
            QCheckBox(), "rd_webrtc_accept_opus_audio",
        )
        self._accept_opus_audio_check.setChecked(False)
        self._accept_opus_audio_check.toggled.connect(
            self._on_toggle_accept_opus_audio,
        )
        self._host_voice_check = self._tr(QCheckBox(), "rd_webrtc_host_voice")
        self._host_voice_check.setChecked(False)
        switches = QWidget()
        switches.setProperty("role", "bare")
        column = QVBoxLayout(switches)
        column.setContentsMargins(0, 0, 0, 0)
        for check in (self._cursor_check, self._blank_check, self._readonly_check, self._adaptive_check,
                      self._mic_recv_check, self._accept_viewer_video_check, self._accept_opus_audio_check,
                      self._host_voice_check):
            column.addWidget(check)
        column.addStretch(1)
        return switches

    def _build_manual_group(self) -> QGroupBox:
        group = self._tr(QGroupBox(), "rd_webrtc_manual_group")
        layout = QVBoxLayout()
        self._generate_btn = self._tr(QPushButton(), "rd_webrtc_generate_offer")
        self._generate_btn.clicked.connect(self._on_generate_offer)
        layout.addLayout(flow_of(self._generate_btn))
        self._offer_view = QTextEdit()
        self._offer_view.setReadOnly(True)
        self._offer_view.setMinimumHeight(80)
        self._answer_input = QTextEdit()
        self._answer_input.setMinimumHeight(80)
        self._tr(self._answer_input, "rd_webrtc_paste_answer", "setPlaceholderText")
        # The offer goes out on the left, the answer comes back on the right.
        layout.addWidget(ResponsiveBox(
            _pane(self._tr(QLabel(), "rd_webrtc_offer_label"), self._offer_view),
            _pane(self._tr(QLabel(), "rd_webrtc_answer_input_label"), self._answer_input)))
        self._apply_btn = self._tr(QPushButton(), "rd_webrtc_apply_answer")
        self._apply_btn.clicked.connect(self._on_apply_answer)
        self._stop_btn = self._tr(QPushButton(), "rd_webrtc_stop_host")
        self._stop_btn.clicked.connect(self._on_stop)
        layout.addLayout(flow_of(self._apply_btn, self._stop_btn))
        group.setLayout(layout)
        return group


__all__ = ["_HostUiMixin"]
