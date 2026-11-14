"""Coordinator that runs one ``WebRTCDesktopHost`` per connected viewer.

Capture (mss + cursor + cursor overlay) happens once; aiortc's
:class:`MediaRelay` distributes the same frames to every active
PeerConnection. Each viewer gets its own DataChannel for input + auth, so
trust list, read-only mode, and accept/reject all keep working unchanged
on a per-viewer basis.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from functools import partial
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

try:
    from aiortc.contrib.media import MediaRelay  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Multi-viewer host requires the 'webrtc' extra (aiortc).",
    ) from exc

from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.remote_desktop.input_dispatch import dispatcher_at
from je_auto_control.utils.remote_desktop.permissions import SessionPermissions
from je_auto_control.utils.remote_desktop.trust_list import TrustList
from je_auto_control.utils.remote_desktop.webrtc_retirement import CleanupAttempt, PeerLifecycleError, PeerStopPending
from je_auto_control.utils.remote_desktop.webrtc_host import WebRTCDesktopHost
from je_auto_control.utils.remote_desktop.webrtc_transport import (
    ScreenVideoTrack, WebRTCConfig,
)


SessionStateCallback = Callable[[str, str], None]
SessionAuthCallback = Callable[[str], None]
SessionPendingCallback = Callable[[str, Optional[str]], None]


class _ScreenSource:
    """Owns a single ScreenVideoTrack + MediaRelay for distribution."""

    def __init__(self, config: WebRTCConfig) -> None:
        self._track = ScreenVideoTrack(
            monitor_index=config.monitor_index,
            fps=config.fps,
            region=config.region,
            show_cursor=config.show_cursor,
        )
        self._relay = MediaRelay()

    def subscribe(self):
        return self._relay.subscribe(self._track)

    @property
    def capture_origin(self) -> Tuple[int, int]:
        """The shared track's frame origin on screen."""
        return self._track.capture_origin

    def stop(self) -> None:
        self._track.stop()


@dataclass(frozen=True)
class SessionRetirement:
    """Retain the original peer and shared source for delayed retirement."""

    session_id: str
    _coordinator: MultiViewerHost
    _peer: WebRTCDesktopHost
    _source: _ScreenSource

    def stop(self) -> None:
        self._coordinator._stop_owned_session(self.session_id, self._peer)
        self._coordinator._maybe_release_source(self._source)


@dataclass(frozen=True)
class OwnedSessionOffer:
    """Offer whose cleanup identity was captured before delivery."""

    retirement: SessionRetirement
    sdp: str

    @property
    def session_id(self) -> str:
        return self.retirement.session_id


class MultiViewerHost:
    """Runs N concurrent ``WebRTCDesktopHost`` instances over one capture.

    Use :meth:`create_session_offer` per incoming viewer to mint a fresh
    session; pass the returned ``session_id`` back into
    :meth:`accept_session_answer`. Existing single-viewer GUI flows can
    keep using ``WebRTCDesktopHost`` directly.
    """

    def __init__(self, *, token: str,
                 config: Optional[WebRTCConfig] = None,
                 trust_list: Optional[TrustList] = None,
                 read_only: bool = False,
                 permissions: Optional[SessionPermissions] = None,
                 input_dispatcher: Optional[Callable[[Mapping[str, Any]], Any]] = None,
                 ip_whitelist: Optional[list] = None,
                 on_annotation: Optional[Callable[[dict], None]] = None,
                 on_session_state: Optional[SessionStateCallback] = None,
                 on_session_authenticated: Optional[SessionAuthCallback] = None,
                 on_pending_viewer: Optional[SessionPendingCallback] = None,
                 ) -> None:
        if not token:
            raise ValueError("MultiViewerHost requires a non-empty token")
        self._token = token
        self._config = config or WebRTCConfig()
        self._trust_list = trust_list
        self._permissions = (
            permissions if permissions is not None
            else SessionPermissions.from_read_only(read_only)
        )
        # The sessions relay one shared track, so they map input by its origin.
        self._dispatch = input_dispatcher or dispatcher_at(self._capture_origin)
        self._ip_whitelist = list(ip_whitelist) if ip_whitelist else []
        self._on_annotation = on_annotation
        self._on_session_state = on_session_state
        self._on_session_authenticated = on_session_authenticated
        self._on_pending_viewer = on_pending_viewer
        self._sessions: Dict[str, WebRTCDesktopHost] = {}
        self._session_meta: Dict[str, dict] = {}
        self._session_tokens: Dict[str, object] = {}
        self._retiring: Dict[str, WebRTCDesktopHost] = {}
        self._creating: set[WebRTCDesktopHost] = set()
        self._source_stopping = False
        self._source_failed = False
        self._source: Optional[_ScreenSource] = None
        self._lock = threading.Lock()

    def _capture_origin(self) -> Tuple[int, int]:
        source = self._source
        return source.capture_origin if source is not None else (0, 0)

    def _annotate(self, data: dict) -> None:
        """Pass a session's annotation on with the shared track's origin.

        A session relays the shared track, so its own origin is (0, 0).
        """
        if self._on_annotation is not None:
            self._on_annotation({**data, "screen_origin": self._capture_origin()})

    # --- session lifecycle --------------------------------------------------

    def create_session_offer(self) -> Tuple[str, str]:
        """Mint a new session: returns ``(session_id, offer_sdp)``."""
        offer = self.create_owned_session_offer()
        return offer.session_id, offer.sdp

    def create_owned_session_offer(self) -> OwnedSessionOffer:
        """Mint an offer with original-resource ownership for delayed delivery."""
        session_id, host, retirement = self._register_session()
        try:
            offer = host.create_offer(peer_label=f"viewer-{session_id[:6]}")
        except BaseException:
            with self._lock:
                self._creating.discard(host)
            retirement.stop()
            raise
        with self._lock:
            self._creating.discard(host)
            retiring = self._retiring.get(session_id) is host
        if retiring:
            retirement.stop()
            raise PeerLifecycleError("session stopped during offer creation")
        return OwnedSessionOffer(retirement, offer)

    def _register_session(self) -> Tuple[str, WebRTCDesktopHost, SessionRetirement]:
        """Build and register one session's peer, or leave nothing behind and raise.

        A peer that fails to build -- the screen subscription or the peer
        itself -- leaves no session token, no relay subscription and, when no
        other session uses it, no running screen source.
        """
        with self._lock:
            if self._retiring or self._source_stopping or self._source_failed:
                raise PeerStopPending("finish retiring previous sessions before creating another")
            if self._source is None:
                self._source = _ScreenSource(self._config)
            source = self._source
            session_id = secrets.token_hex(8)
            if session_id in self._sessions:
                raise PeerLifecycleError("session identity collision")
            token = object()
            self._session_tokens[session_id] = token
            try:
                host = self._new_session_peer(session_id, token, source)
            except BaseException as error:  # noqa: BLE001  # reason: re-raised below, after the source is released
                self._session_tokens.pop(session_id, None)
                failure = error
            else:
                self._sessions[session_id] = host
                self._creating.add(host)
                return session_id, host, SessionRetirement(session_id, self, host, source)
        self._release_unused_source(source)
        raise failure

    def _new_session_peer(self, session_id: str, token: object, source: _ScreenSource) -> WebRTCDesktopHost:
        """Subscribe to the shared screen and build one session's peer; a failed build drops its subscription."""
        track = source.subscribe()
        try:
            return WebRTCDesktopHost(
                token=self._token,
                config=self._config,
                trust_list=self._trust_list,
                permissions=self._permissions,
                input_dispatcher=self._dispatch,
                ip_whitelist=self._ip_whitelist,
                on_annotation=self._annotate if self._on_annotation is not None else None,
                external_video_track=track,
                on_state_change=self._wrap_state_callback(session_id, token),
                on_authenticated=self._wrap_auth_callback(session_id, token),
                on_pending_viewer=self._wrap_pending_callback(session_id, token),
            )
        except BaseException:
            stop = getattr(track, "stop", None)
            if callable(stop):
                stop()
            raise

    def _release_unused_source(self, source: _ScreenSource) -> None:
        """After a session failed to build: stop the screen source if no session uses it (it may be new)."""
        try:
            self._maybe_release_source(source)
        except (RuntimeError, OSError) as error:   # the build's own error is the one to raise
            autocontrol_logger.warning("releasing the screen source after a failed session: %r", error)

    def session_retirement(self, session_id: str) -> SessionRetirement:
        """Capture the currently registered generation before queuing cleanup."""
        with self._lock:
            host = self._sessions[session_id]
            source = self._source
            if source is None:
                raise PeerLifecycleError("session has no owned screen source")
            return SessionRetirement(session_id, self, host, source)

    def accept_session_answer(self, session_id: str, answer_sdp: str) -> None:
        host = self._require_session(session_id)
        host.accept_answer(answer_sdp)

    def stop_session(self, session_id: str) -> None:
        with self._lock:
            host = self._sessions.get(session_id)
            source = self._source
        if host is not None:
            self._stop_owned_session(session_id, host)
        self._maybe_release_source(source)

    def _stop_owned_session(self, session_id: str, host: WebRTCDesktopHost) -> None:
        with self._lock:
            if self._sessions.get(session_id) is not host:
                return
            self._retiring[session_id] = host
            if host in self._creating:
                raise PeerStopPending("session offer creation is still running")
        host.stop()
        with self._lock:
            if self._sessions.get(session_id) is host:
                self._sessions.pop(session_id)
                self._session_meta.pop(session_id, None)
                self._session_tokens.pop(session_id, None)
            if self._retiring.get(session_id) is host:
                self._retiring.pop(session_id)

    def stop_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.items())
            self._retiring.update(sessions)
            source = self._source
        attempt = CleanupAttempt()
        for session_id, host in sessions:
            attempt.run(partial(self._stop_owned_session, session_id, host), "session")
        attempt.run(partial(self._maybe_release_source, source), "screen source")
        attempt.finish()

    def _maybe_release_source(self, expected: Optional[_ScreenSource]) -> None:
        with self._lock:
            if self._sessions or self._source is None or self._source is not expected:
                return
            if self._source_stopping:
                raise PeerStopPending("screen source stop is still running")
            source = self._source
            self._source_stopping = True
            self._source_failed = True
        try:
            source.stop()
        except BaseException:
            with self._lock:
                self._source_stopping = False
            raise
        with self._lock:
            if self._source is source:
                self._source = None
            self._source_stopping = self._source_failed = False

    # --- per-session controls -----------------------------------------------

    def approve_pending_viewer(self, session_id: str) -> None:
        self._require_session(session_id).approve_pending_viewer()

    def reject_pending_viewer(self, session_id: str) -> None:
        self._require_session(session_id).reject_pending_viewer()

    def trust_pending_viewer(self, session_id: str, label: str = "") -> None:
        self._require_session(session_id).trust_pending_viewer(label=label)

    def pending_viewer_id(self, session_id: str) -> Optional[str]:
        return self._require_session(session_id).pending_viewer_id

    def set_read_only(self, value: bool) -> None:
        """Backwards-compat shim around :meth:`set_permissions`."""
        self.set_permissions(SessionPermissions.from_read_only(bool(value)))

    def set_permissions(self, permissions: SessionPermissions) -> None:
        """Update permissions for new sessions and propagate to active ones."""
        self._permissions = permissions
        with self._lock:
            sessions = list(self._sessions.values())
        for host in sessions:
            try:
                host.set_permissions(permissions)
            except (RuntimeError, OSError) as error:
                autocontrol_logger.debug("permissions set: %r", error)

    @property
    def permissions(self) -> SessionPermissions:
        return self._permissions

    def disable_accept_viewer_video(self) -> None:
        """Inactivate the recvonly video slot on every active session."""
        with self._lock:
            sessions = list(self._sessions.values())
        for host in sessions:
            try:
                host.disable_accept_viewer_video()
            except (RuntimeError, OSError) as error:
                autocontrol_logger.debug("disable accept video: %r", error)

    def disable_accept_viewer_audio_opus(self) -> None:
        """Inactivate the recvonly audio slot on every active session."""
        with self._lock:
            sessions = list(self._sessions.values())
        for host in sessions:
            try:
                host.disable_accept_viewer_audio_opus()
            except (RuntimeError, OSError) as error:
                autocontrol_logger.debug("disable accept audio: %r", error)

    def broadcast_file(self, local_path, remote_name=None) -> int:
        """Push a file to every authenticated viewer; returns recipient count."""
        with self._lock:
            sessions = list(self._sessions.values())
        sent = 0
        for host in sessions:
            if not host.authenticated:
                continue
            try:
                host.push_file(local_path, remote_name=remote_name)
                sent += 1
            except (RuntimeError, OSError, ValueError) as error:
                autocontrol_logger.warning("broadcast_file: %r", error)
        return sent

    # --- introspection ------------------------------------------------------

    def list_sessions(self) -> List[dict]:
        with self._lock:
            return [
                {
                    "session_id": sid,
                    "authenticated": host.authenticated,
                    "state": host.connection_state,
                    "pending_viewer_id": host.pending_viewer_id,
                    "connected_at": (
                        self._session_meta.get(sid, {}).get("connected_at")
                    ),
                }
                for sid, host in self._sessions.items()
            ]

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def screen_track(self):
        """Return the underlying ``ScreenVideoTrack`` (or None if no source)."""
        with self._lock:
            return None if self._source is None else self._source._track

    def first_session_pc(self):
        """Return the first session's RTCPeerConnection, or None."""
        with self._lock:
            for host in self._sessions.values():
                if host._pc is not None:
                    return host._pc
            return None

    def session_pc(self, session_id: str):
        """Return the named session's RTCPeerConnection, or None if gone."""
        with self._lock:
            host = self._sessions.get(session_id)
        return host._pc if host is not None else None

    def _require_session(self, session_id: str) -> WebRTCDesktopHost:
        with self._lock:
            if session_id in self._retiring:
                raise PeerStopPending("session is retiring")
            host = self._sessions.get(session_id)
        if host is None:
            raise KeyError(f"unknown session_id: {session_id}")
        return host

    # --- callback wrappers --------------------------------------------------

    def _wrap_state_callback(self, session_id: str, token: object = None):
        cb = self._on_session_state
        def _emit(state: str) -> None:
            if token is not None and self._session_tokens.get(session_id) is not token:
                return
            if state in _FINAL_STATES:
                self._prune_later(session_id, token)
            if cb is None:
                return
            try:
                cb(session_id, state)
            except (RuntimeError, OSError) as error:
                autocontrol_logger.debug("session state cb: %r", error)
        return _emit

    def _prune_later(self, session_id: str, token: object = None) -> None:
        """Drop a session whose peer connection ended, off the loop thread.

        A peer that fails, closes, or misses the auth deadline is stopped
        inside its host, but this registry kept the entry: ``session_count``
        only grew and the screen source was never released, so capture ran
        on with nobody watching. ``stop_session`` blocks on the bridge, and
        this is called from the loop thread, hence the thread.
        """
        with self._lock:
            if token is not None and self._session_tokens.get(session_id) is not token:
                return
            host = self._sessions.get(session_id)
            source = self._source
        if host is None:
            return
        def retire() -> None:
            try:
                self._stop_owned_session(session_id, host)
                self._maybe_release_source(source)
            except (RuntimeError, OSError):
                autocontrol_logger.warning("session retirement remains pending")
        threading.Thread(target=retire, name="webrtc-prune", daemon=True).start()

    def _wrap_auth_callback(self, session_id: str, token: object = None):
        cb = self._on_session_authenticated
        def _emit() -> None:
            with self._lock:
                if token is not None and self._session_tokens.get(session_id) is not token:
                    return
                meta = self._session_meta.setdefault(session_id, {})
                meta["connected_at"] = datetime.now(timezone.utc).isoformat()
            if cb is None:
                return
            try:
                cb(session_id)
            except (RuntimeError, OSError) as error:
                autocontrol_logger.debug("session auth cb: %r", error)
        return _emit

    def _wrap_pending_callback(self, session_id: str, token: object = None):
        cb = self._on_pending_viewer
        if cb is None:
            return None
        def _emit() -> None:
            with self._lock:
                if token is not None and self._session_tokens.get(session_id) is not token:
                    return
                host = self._sessions.get(session_id)
                viewer_id = host.pending_viewer_id if host is not None else None
            try:
                cb(session_id, viewer_id)
            except (RuntimeError, OSError) as error:
                autocontrol_logger.debug("pending cb: %r", error)
        return _emit


#: Peer-connection states after which a session is over for good.
#: ``disconnected`` is left out on purpose: ICE can recover from it.
_FINAL_STATES = frozenset({"failed", "closed"})


__all__ = ["MultiViewerHost", "OwnedSessionOffer", "SessionRetirement"]
