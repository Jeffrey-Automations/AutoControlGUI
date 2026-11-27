"""``_HostPanel``: the 'host this machine' Remote Desktop sub-tab."""
import functools
import secrets
from typing import Any, Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from je_auto_control.gui._authorize import RefusalLabel
from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._latest_decoder import LatestDecoder, decode_jpeg
from je_auto_control.gui._secret_field import SecretField
from je_auto_control.gui._slow_op import SlowOp
from je_auto_control.gui.adaptive.flow_layout import field_pair, flow_of
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.remote_desktop._host_ops import (
    HostTlsError, release_host, replace_host, replace_tls_host, stop_host,
)
from je_auto_control.gui.remote_desktop.view_lifetime import ViewLifetime
from je_auto_control.gui.remote_desktop._helpers import (
    _CollapsibleSection, _StatusBadge, _t,
)
from je_auto_control.gui.remote_desktop.frame_display import _FrameDisplay
from je_auto_control.utils.remote_desktop import (
    RemoteDesktopHost, WebSocketDesktopHost,
)
from je_auto_control.utils.remote_desktop.audio import (
    AudioCaptureConfig, is_audio_backend_available,
)
from je_auto_control.utils.remote_desktop.host_admission import (
    DEFAULT_AUTH_TIMEOUT_S, DEFAULT_MAX_PENDING_HANDSHAKES,
)
from je_auto_control.utils.remote_desktop.host_id import format_host_id
from je_auto_control.utils.remote_desktop.registry import (
    SLOT_HOST, new_owner, registry,
)



class _HostPanel(TranslatableMixin, QWidget):
    """Start / stop the singleton host and show what is being streamed."""

    #: Checked against the active RBAC role when the page is shown.
    REQUIRED_COMMANDS = ("AC_start_remote_host", "AC_stop_remote_host", "AC_start_ws_host", "AC_stop_ws_host")

    _PREVIEW_INTERVAL_MS = 250  # 4 fps preview is enough to confirm liveness

    # Another owner replaced or stopped the host this panel started.
    _displaced = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._view = ViewLifetime(self)
        self._owner = new_owner("host-tab")
        self._displaced.connect(self._on_displaced)
        # Start and Stop both stop a host, which joins its threads.
        self._host_op = SlowOp(self)
        self._pending_key = "gui_op_stopping"
        # The share details of the start that is out; they become _shared when it reports.
        self._starting: dict[str, str] = {}
        self._host_id_label = QLabel("---")
        self._host_id_label.setStyleSheet(
            "font-family: 'Consolas', 'Menlo', 'Courier New', monospace; "
            "font-size: 26pt; font-weight: bold; "
            "letter-spacing: 2px;"
        )
        set_role(self._host_id_label, "accent")
        self._badge = _StatusBadge()
        self._token = QLineEdit()
        self._bind = QLineEdit("127.0.0.1")
        self._port = QSpinBox()
        self._port.setRange(0, 65535)
        self._port.setValue(0)
        self._transport = QComboBox()
        self._transport.addItems(["TCP", "WebSocket"])
        self._fps = QSpinBox()
        self._fps.setRange(1, 60)
        self._fps.setValue(10)
        self._quality = QSpinBox()
        self._quality.setRange(1, 95)
        self._quality.setValue(70)
        # Connections still authenticating, and how long each has (the host
        # refuses a deadline over 60 s, so the field does too).
        self._max_pending = QSpinBox()
        self._max_pending.setRange(1, 64)
        self._max_pending.setValue(DEFAULT_MAX_PENDING_HANDSHAKES)
        self._auth_timeout = QDoubleSpinBox()
        self._auth_timeout.setRange(1.0, 60.0)
        self._auth_timeout.setDecimals(1)
        self._auth_timeout.setSingleStep(1.0)
        self._auth_timeout.setValue(DEFAULT_AUTH_TIMEOUT_S)
        self._tls_cert = QLineEdit()
        self._tls_key = QLineEdit()
        self._enable_audio = QCheckBox()
        self._enable_audio.setChecked(False)
        # A flag, not isEnabled(): the collapsed Advanced section disables it.
        self._audio_available = is_audio_backend_available()
        if not self._audio_available:
            self._enable_audio.setEnabled(False)
        # What the share text quotes, taken at Start (see _copy_share_text).
        self._shared: Optional[dict[str, Any]] = None
        self._preview = _FrameDisplay()
        # Preview is read-only — a host watching their own stream shouldn't
        # trigger fake input on themselves through the local widget.
        self._preview.setEnabled(False)
        # Preview frames are decoded on a thread of this panel's own; a clear
        # bumps the generation so a frame still being decoded is not painted.
        self._preview_decoder = LatestDecoder(self, decode_jpeg, self._on_preview_decoded)
        self._preview_generation = 0
        self._preview_source: Optional[bytes] = None
        self._start_btn: Optional[QPushButton] = None
        self._stop_btn: Optional[QPushButton] = None
        self._copy_id_btn: Optional[QPushButton] = None
        self._copy_share_btn: Optional[QPushButton] = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._refresh_status)
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(self._PREVIEW_INTERVAL_MS)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._build_layout()
        self._apply_placeholders()
        self._refresh_status()
        self._refresh_timer.start()
        self._preview_timer.start()

    def dispose(self) -> None:
        """Release what the tab holds beyond its widgets: its status and preview timers (the host keeps running).

        Called by ``close_tab(key)`` before the widget is deleted; safe to call twice.
        """
        self._view.retire()
        release_resources(self._host_op)
        release_resources(self, self._preview_decoder.stop)

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        self._apply_placeholders()
        self._refresh_status()

    def _apply_placeholders(self) -> None:
        self._token.setPlaceholderText(_t("rd_token_placeholder"))
        self._tls_cert.setPlaceholderText(_t("rd_tls_cert_placeholder"))
        self._tls_key.setPlaceholderText(_t("rd_tls_key_placeholder"))

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        warning = QLabel()
        warning.setWordWrap(True)
        set_role(warning, "warning")
        self._tr(warning, "rd_host_security_warning")
        root.addWidget(warning)
        self._refusal = RefusalLabel()
        root.addWidget(self._refusal)

        root.addWidget(self._build_card())
        root.addWidget(self._build_basics())
        root.addWidget(self._build_advanced())

        # === Primary action row ===
        btn_row = QHBoxLayout()
        self._start_btn = self._tr(QPushButton(), "rd_host_start")
        self._start_btn.setMinimumHeight(36)
        self._start_btn.setStyleSheet("font-weight: bold;")
        self._start_btn.clicked.connect(self._start)
        self._stop_btn = self._tr(QPushButton(), "rd_host_stop")
        self._stop_btn.setMinimumHeight(36)
        self._stop_btn.clicked.connect(self._stop)
        self._host_op.busy_changed.connect(self._start_btn.setDisabled)
        self._host_op.busy_changed.connect(self._stop_btn.setDisabled)
        btn_row.addWidget(self._start_btn, stretch=2)
        btn_row.addWidget(self._stop_btn, stretch=1)
        root.addLayout(btn_row)

        # === Preview ===
        preview = Card("rd_host_preview_label")
        preview.add(self._preview, stretch=1)
        root.addWidget(preview, stretch=1)

    def _build_card(self) -> QGroupBox:
        """The connection card — the focal point: Host ID, token and the copy buttons."""
        card = self._tr(QGroupBox(), "rd_host_card_group")
        card.setStyleSheet("QGroupBox { font-weight: bold; }")
        card_layout = QVBoxLayout()
        form = QFormLayout()
        id_row = QHBoxLayout()
        id_row.addWidget(self._host_id_label, stretch=1)
        id_row.addWidget(self._badge)
        form.addRow(self._tr(QLabel(), "rd_host_id_label"), id_row)
        token_row = QHBoxLayout()
        token_row.addWidget(SecretField(self._token, self._tr), stretch=1)
        gen_btn = self._tr(QPushButton(), "rd_token_generate")
        gen_btn.clicked.connect(self._generate_token)
        token_row.addWidget(gen_btn)
        form.addRow(self._tr(QLabel(), "rd_token_label"), token_row)
        card_layout.addLayout(form)

        self._copy_id_btn = self._tr(QPushButton(), "rd_host_id_copy")
        self._copy_id_btn.clicked.connect(self._copy_host_id)
        self._copy_share_btn = self._tr(QPushButton(), "rd_host_copy_share")
        self._copy_share_btn.clicked.connect(self._copy_share_text)
        card_layout.addLayout(flow_of(self._copy_id_btn, self._copy_share_btn))
        card.setLayout(card_layout)
        return card

    def _build_basics(self) -> QGroupBox:
        """Basic connection settings: bind address, port and transport, wrapping when narrow."""
        basics = self._tr(QGroupBox(), "rd_host_basics_group")
        basics_layout = QVBoxLayout()
        basics_layout.addLayout(flow_of(*(field_pair(self._tr(QLabel(), key), field) for key, field in (
            ("rd_bind_label", self._bind), ("rd_port_label", self._port),
            ("rd_transport_label", self._transport)))))
        basics.setLayout(basics_layout)
        return basics

    def _build_advanced(self) -> _CollapsibleSection:
        """The collapsible TLS / media / audio section."""
        advanced = _CollapsibleSection()
        self._tr(advanced, "rd_advanced_group", setter="setTitle")
        adv_layout = QVBoxLayout()
        form = QFormLayout()
        for label_key, field, slot in (("rd_tls_cert_label", self._tls_cert, self._browse_cert),
                                       ("rd_tls_key_label", self._tls_key, self._browse_key)):
            row = QHBoxLayout()
            row.addWidget(field, stretch=1)
            browse = self._tr(QPushButton(), "rd_browse")
            browse.clicked.connect(slot)
            row.addWidget(browse)
            form.addRow(self._tr(QLabel(), label_key), row)
        adv_layout.addLayout(form)
        adv_layout.addLayout(flow_of(*(field_pair(self._tr(QLabel(), key), field) for key, field in (
            ("rd_fps_label", self._fps), ("rd_quality_label", self._quality),
            ("rd_max_pending_label", self._max_pending), ("rd_auth_timeout_label", self._auth_timeout)))))
        self._tr(self._max_pending, "rd_max_pending_tooltip", setter="setToolTip")
        self._tr(self._auth_timeout, "rd_auth_timeout_tooltip", setter="setToolTip")
        adv_layout.addWidget(self._tr(self._enable_audio, "rd_enable_audio"))
        advanced.set_body_layout(adv_layout)
        return advanced

    def _generate_token(self) -> None:
        self._token.setText(secrets.token_urlsafe(24))

    def _copy_host_id(self) -> None:
        host = registry.host
        if host is None:
            return
        QGuiApplication.clipboard().setText(format_host_id(host.host_id))

    def _copy_share_text(self) -> None:
        """Copy a one-line bundle of address / port / token / id (token leak risk).

        The details are the ones this panel started the host with. Read from
        the fields at copy time, an edited token or transport sent a viewer
        details the running host refuses, and a host started elsewhere was
        shared with this panel's token.
        """
        host = registry.host
        shared = self._shared
        if host is None or shared is None or shared["host"] is not host:
            QMessageBox.information(
                self, _t("rd_host_copy_share"),
                _t("rd_host_copy_share_unavailable"),
            )
            return
        confirm = QMessageBox.question(
            self, _t("rd_host_copy_share"),
            _t("rd_host_copy_share_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        bundle = (
            f"AutoControl Remote Desktop\n"
            f"Host ID: {format_host_id(host.host_id)}\n"
            f"Address: {shared['bind']}\n"
            f"Port:    {host.port}\n"
            f"Transport: {shared['transport']}\n"
            f"Token:   {shared['token']}"
        )
        QGuiApplication.clipboard().setText(bundle)

    def _browse_cert(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, _t("rd_tls_cert_label"), "",
            "PEM (*.pem *.crt *.cer);;All (*)",
        )
        if path:
            self._tls_cert.setText(path)

    def _browse_key(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, _t("rd_tls_key_label"), "",
            "PEM (*.pem *.key);;All (*)",
        )
        if path:
            self._tls_key.setText(path)

    def _tls_paths(self) -> Optional[tuple[str, str]]:
        """The certificate and key to serve TLS with, or ``None`` for neither; the files are read by the start."""
        cert_path = self._tls_cert.text().strip()
        key_path = self._tls_key.text().strip()
        if not cert_path and not key_path:
            return None
        if not cert_path or not key_path:
            raise ValueError(_t("rd_tls_both_required"))
        return cert_path, key_path

    def _start(self) -> None:
        if self._host_op.busy:          # a start or stop is still out; a second click is ignored
            return
        transport = self._transport.currentText()
        if not self._refusal.allows("AC_start_ws_host" if transport == "WebSocket" else "AC_start_remote_host"):
            return
        token = self._token.text().strip()
        if not token:
            self._generate_token()
            token = self._token.text().strip()
        try:
            tls = self._tls_paths()
        except ValueError as error:
            QMessageBox.warning(self, _t("rd_host_start"), str(error))
            return
        host_cls = (WebSocketDesktopHost if transport == "WebSocket"
                    else RemoteDesktopHost)
        bind = self._bind.text().strip() or "127.0.0.1"
        build = functools.partial(
            host_cls,
            token=token,
            bind=bind,
            port=self._port.value(),
            fps=float(self._fps.value()),
            quality=self._quality.value(),
            max_pending_handshakes=self._max_pending.value(),
            auth_timeout=float(self._auth_timeout.value()),
            ssl_context=None,
            audio_config=AudioCaptureConfig(
                enabled=self._audio_available and self._enable_audio.isChecked(),
            ),
        )
        # The transport a viewer picks: with a certificate, TCP is TLS and
        # WebSocket is WSS, which the share text used to call TCP / WebSocket.
        on_displaced = self._view.callback("_on_displaced")
        work = functools.partial(replace_host, self._owner, build, on_displaced)
        if tls is not None:
            transport = {"TCP": "TLS", "WebSocket": "WSS"}[transport]
            # The chain is read on the start's worker, before the running host is stopped.
            work = functools.partial(replace_tls_host, self._owner, *tls, build, on_displaced)
        self._starting = {"bind": bind, "transport": transport, "token": token}
        self._pending_key = "gui_op_starting"
        self._host_op.run(
            work, on_done=self._on_started, on_error=self._on_start_failed,
            discard=functools.partial(release_host, self._owner))
        self._refresh_status()

    def _on_started(self, host: Any) -> None:
        """GUI thread: the host is up and registered for this panel."""
        self._shared = {"host": host, **self._starting}
        self._refresh_status()

    def _on_start_failed(self, error: Exception) -> None:
        if not isinstance(error, HostTlsError):     # a certificate that did not load stopped nothing
            self._shared = None
        self._refresh_status()
        QMessageBox.warning(self, _t("rd_host_start"), str(error))

    def _stop(self) -> None:
        # The badge shows the machine's host whoever started it, so Stop stops
        # that one: a visible "running" with a Stop that does nothing would be
        # worse on a remote-access surface. Its owner is told.
        if self._host_op.busy:          # a second click while the first is still stopping
            return
        # Either transport's host may be the one running; both commands need the same capability.
        if not self._refusal.allows("AC_stop_remote_host", "AC_stop_ws_host"):
            return
        self._pending_key = "gui_op_stopping"
        self._host_op.run(functools.partial(stop_host, self._owner), on_done=self._on_stopped,
                          on_error=self._on_stop_failed, retain_failure=True)
        self._refresh_status()

    def _on_stopped(self, _evicted: object = None) -> None:
        self._shared = None
        self._refresh_status()

    def _on_stop_failed(self, error: Exception) -> None:
        self._refresh_status()
        QMessageBox.warning(self, _t("rd_host_stop"), str(error))

    def _on_displaced(self, _slot: str, _by: str) -> None:
        """GUI thread: the host this panel started was replaced or stopped."""
        if registry.owned(SLOT_HOST, self._owner) is None:
            self._shared = None
        self._refresh_status()

    def _refresh_status(self) -> None:
        if self._host_op.busy:
            self._badge.set_state("starting", _t(self._pending_key))
            return
        status = registry.host_status()
        if status["running"]:
            host_id = status.get("host_id") or ""
            self._host_id_label.setText(
                format_host_id(host_id) if host_id else "---"
            )
            self._badge.set_state(
                "running",
                _t("rd_badge_running")
                .replace("{port}", str(status["port"]))
                .replace("{n}", str(status["connected_clients"])),
            )
        else:
            self._host_id_label.setText("---")
            self._badge.set_state("stopped", _t("rd_badge_stopped"))

    def _refresh_preview(self) -> None:
        # Four JPEG decodes a second for a panel nobody can see.
        if not self.isVisible():
            return
        host = registry.host
        if host is None or not host.is_running:
            self._preview_generation += 1
            self._preview_source = None
            self._preview.clear()
            return
        frame = host.latest_frame()
        if frame is None or frame is self._preview_source:
            return                          # nothing new since the last tick
        self._preview_source = frame
        self._preview_decoder.submit(frame, self._preview_generation)

    def _on_preview_decoded(self, generation: int, image: QImage) -> None:
        if generation == self._preview_generation and not image.isNull():
            self._preview.set_image(image)
