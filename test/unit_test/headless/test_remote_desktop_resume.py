"""Phase 6.6: tests for the resume-token reconnect path."""
import time
from io import BytesIO

import pytest

from je_auto_control.utils.remote_desktop.host import RemoteDesktopHost
from je_auto_control.utils.remote_desktop.host_access import PendingViewer
from je_auto_control.utils.remote_desktop.resume_tokens import (
    ResumeTokenStore,
)
from je_auto_control.utils.remote_desktop.viewer import RemoteDesktopViewer


def _jpeg() -> bytes:
    from PIL import Image
    img = Image.new("RGB", (16, 16), color=(0, 0, 0))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


# --- ResumeTokenStore unit tests ---------------------------------------

def test_issue_and_consume_round_trip():
    store = ResumeTokenStore(ttl=60.0)
    token = store.issue(permission="view_only")
    assert isinstance(token, str)
    assert len(token) > 16
    assert store.consume(token) == "view_only"
    # Second consume returns None — single-use semantics.
    assert store.consume(token) is None


def test_consume_unknown_token_returns_none():
    assert ResumeTokenStore().consume("not-a-real-token") is None


def test_expired_token_is_not_consumable():
    store = ResumeTokenStore(ttl=0.05)
    token = store.issue()
    time.sleep(0.1)
    assert store.consume(token) is None


def test_list_active_excludes_expired():
    store = ResumeTokenStore(ttl=0.05)
    fresh = store.issue()
    time.sleep(0.1)
    stale_recovered = store.list_active()
    assert fresh not in stale_recovered


def test_remove_returns_true_for_present_token():
    store = ResumeTokenStore()
    token = store.issue()
    assert store.remove(token) is True
    assert store.remove(token) is False


# --- End-to-end host/viewer reconnect ----------------------------------

def test_viewer_receives_resume_token_in_auth_ok():
    host = RemoteDesktopHost(
        token="tok", bind="127.0.0.1", port=0, fps=30.0,
        frame_provider=_jpeg,
    )
    host.start()
    try:
        viewer = RemoteDesktopViewer(
            host="127.0.0.1", port=host.port, token="tok",
        )
        viewer.connect(timeout=5.0)
        try:
            assert viewer.resume_token is not None
            assert len(viewer.resume_token) > 16
            assert viewer.resume_ttl == host._resume_store.ttl
        finally:
            viewer.disconnect(timeout=1.0)
    finally:
        host.stop(timeout=1.0)


def test_reconnect_with_resume_token_skips_approval_popup():
    """A reconnect with the saved resume token must not fire the callback."""
    approval_calls = []

    def gate(p: PendingViewer):
        approval_calls.append(p)
        return True

    host = RemoteDesktopHost(
        token="tok", bind="127.0.0.1", port=0, fps=30.0,
        frame_provider=_jpeg, on_pending_viewer=gate,
    )
    host.start()
    try:
        v1 = RemoteDesktopViewer(
            host="127.0.0.1", port=host.port, token="tok",
        )
        v1.connect(timeout=5.0)
        first_resume = v1.resume_token
        v1.disconnect(timeout=1.0)
        assert len(approval_calls) == 1
        # Reconnect with the resume token instead of the original.
        v2 = RemoteDesktopViewer(
            host="127.0.0.1", port=host.port, token=first_resume,
        )
        v2.connect(timeout=5.0)
        try:
            # The approval callback must NOT have fired again.
            assert len(approval_calls) == 1
            # Viewer also got a brand-new resume token for the next hop.
            assert v2.resume_token is not None
            assert v2.resume_token != first_resume
        finally:
            v2.disconnect(timeout=1.0)
    finally:
        host.stop(timeout=1.0)


def test_resume_preserves_view_only_permission():
    """A view-only session that resumes must remain view-only."""
    host = RemoteDesktopHost(
        token="tok", bind="127.0.0.1", port=0, fps=30.0,
        frame_provider=_jpeg,
        on_pending_viewer=lambda _p: "view_only",
    )
    host.start()
    try:
        v1 = RemoteDesktopViewer(
            host="127.0.0.1", port=host.port, token="tok",
        )
        v1.connect(timeout=5.0)
        saved = v1.resume_token
        v1.disconnect(timeout=1.0)
        # Reconnect via resume — handler should still be view_only.
        v2 = RemoteDesktopViewer(
            host="127.0.0.1", port=host.port, token=saved,
        )
        v2.connect(timeout=5.0)
        try:
            # Send input — it should be silently dropped (view-only).
            captured = []
            host._dispatch = captured.append  # noqa: SLF001  test inspection
            v2.send_input({"action": "mouse_move", "x": 1, "y": 1})
            time.sleep(0.3)
            assert captured == []
        finally:
            v2.disconnect(timeout=1.0)
    finally:
        host.stop(timeout=1.0)


def test_resume_token_is_consumed_after_use():
    """A second reconnect with the same token must fail."""
    from je_auto_control.utils.remote_desktop.protocol import (
        AuthenticationError,
    )
    host = RemoteDesktopHost(
        token="tok", bind="127.0.0.1", port=0, fps=30.0,
        frame_provider=_jpeg,
    )
    host.start()
    try:
        v1 = RemoteDesktopViewer(
            host="127.0.0.1", port=host.port, token="tok",
        )
        v1.connect(timeout=5.0)
        saved = v1.resume_token
        v1.disconnect(timeout=1.0)
        # First resume works.
        v2 = RemoteDesktopViewer(
            host="127.0.0.1", port=host.port, token=saved,
        )
        v2.connect(timeout=5.0)
        v2.disconnect(timeout=1.0)
        # Second resume with the *same* token must fail.
        v3 = RemoteDesktopViewer(
            host="127.0.0.1", port=host.port, token=saved,
        )
        with pytest.raises((AuthenticationError, OSError, ConnectionError)):
            v3.connect(timeout=2.0)
    finally:
        host.stop(timeout=1.0)


def test_two_connections_cannot_both_spend_one_resume_token(monkeypatch):
    """Both read the table before either removed the token; the removal's answer was ignored."""
    from je_auto_control.utils.remote_desktop.auth import compute_response, make_nonce
    host = RemoteDesktopHost(token="tok", bind="127.0.0.1", port=0, frame_provider=_jpeg)
    token = host._resume_store.issue("full")
    stale = host._resume_store.list_active()
    monkeypatch.setattr(host._resume_store, "list_active", lambda: dict(stale))
    grants = []
    for _connection in range(2):
        nonce = make_nonce()
        grants.append(host._try_consume_resume(nonce, compute_response(token, nonce)))
    assert grants == ["full", None]


def test_stopping_the_host_invalidates_its_resume_tokens():
    """The store promises a restart does; a stopped and started host kept honouring them."""
    from je_auto_control.utils.remote_desktop.protocol import AuthenticationError
    host = RemoteDesktopHost(token="tok", bind="127.0.0.1", port=0, fps=30.0, frame_provider=_jpeg)
    host.start()
    try:
        viewer = RemoteDesktopViewer(host="127.0.0.1", port=host.port, token="tok")
        viewer.connect(timeout=5.0)
        saved = viewer.resume_token
        viewer.disconnect(timeout=1.0)
        host.stop(timeout=1.0)
        host.start()
        again = RemoteDesktopViewer(host="127.0.0.1", port=host.port, token=saved)
        with pytest.raises(AuthenticationError):
            again.connect(timeout=3.0)
    finally:
        host.stop(timeout=1.0)
