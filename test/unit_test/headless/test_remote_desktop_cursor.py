"""Headless tests for the host->viewer cursor-position broadcast."""
import threading
import time
from io import BytesIO

import pytest

from je_auto_control.utils.remote_desktop.host import RemoteDesktopHost
from je_auto_control.utils.remote_desktop.viewer import RemoteDesktopViewer


def _make_jpeg() -> bytes:
    from PIL import Image
    img = Image.new("RGB", (32, 24), color=(50, 50, 50))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


@pytest.fixture
def jpeg_bytes():
    return _make_jpeg()


def test_host_broadcasts_cursor_to_viewer(jpeg_bytes):
    """Each unique position the cursor reports reaches the viewer."""
    positions = iter([
        (10, 20), (10, 20), (15, 30), (15, 30), (200, 100),
    ])

    def cursor_provider():
        try:
            return next(positions)
        except StopIteration:
            return None

    received = []
    received_lock = threading.Lock()

    def on_cursor(x: int, y: int) -> None:
        with received_lock:
            received.append((x, y))

    host = RemoteDesktopHost(
        token="t", bind="127.0.0.1", port=0, fps=30.0,
        frame_provider=lambda: jpeg_bytes,
        cursor_provider=cursor_provider,
    )
    host.start()
    try:
        viewer = RemoteDesktopViewer(
            host="127.0.0.1", port=host.port, token="t",
            on_cursor=on_cursor,
        )
        viewer.connect(timeout=5.0)
        try:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                with received_lock:
                    if (10, 20) in received \
                            and (15, 30) in received \
                            and (200, 100) in received:
                        break
                time.sleep(0.05)
            with received_lock:
                snapshot = list(received)
            # Each unique position arrived; dedupe of consecutive
            # duplicates happened on the host side so the viewer never
            # sees back-to-back identical updates for a still cursor.
            assert (10, 20) in snapshot
            assert (15, 30) in snapshot
            assert (200, 100) in snapshot
        finally:
            viewer.disconnect(timeout=1.0)
    finally:
        host.stop(timeout=1.0)


def test_cursor_broadcast_disabled_keeps_viewer_callback_silent(jpeg_bytes):
    """``enable_cursor_broadcast=False`` should suppress CURSOR messages."""
    received = []
    received_lock = threading.Lock()

    def on_cursor(x: int, y: int) -> None:
        with received_lock:
            received.append((x, y))

    host = RemoteDesktopHost(
        token="t", bind="127.0.0.1", port=0, fps=30.0,
        frame_provider=lambda: jpeg_bytes,
        enable_cursor_broadcast=False,
    )
    host.start()
    try:
        viewer = RemoteDesktopViewer(
            host="127.0.0.1", port=host.port, token="t",
            on_cursor=on_cursor,
        )
        viewer.connect(timeout=5.0)
        try:
            # Give the (would-be) cursor thread plenty of poll cycles.
            time.sleep(0.5)
            with received_lock:
                assert received == []
        finally:
            viewer.disconnect(timeout=1.0)
    finally:
        host.stop(timeout=1.0)


def test_cursor_provider_returning_none_is_safe(jpeg_bytes):
    """A broken cursor provider should not crash the host."""
    host = RemoteDesktopHost(
        token="t", bind="127.0.0.1", port=0, fps=30.0,
        frame_provider=lambda: jpeg_bytes,
        cursor_provider=lambda: None,
    )
    host.start()
    try:
        viewer = RemoteDesktopViewer(
            host="127.0.0.1", port=host.port, token="t",
        )
        viewer.connect(timeout=5.0)
        try:
            # Host still streams frames despite the dead cursor provider.
            time.sleep(0.3)
            assert viewer.connected
        finally:
            viewer.disconnect(timeout=1.0)
    finally:
        host.stop(timeout=1.0)


def test_frame_display_paints_cursor_overlay():
    """Setting the remote cursor must mutate state + trigger update."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication([])
    from je_auto_control.gui.remote_desktop.frame_display import _FrameDisplay

    display = _FrameDisplay()
    try:
        assert display._remote_cursor is None  # noqa: SLF001
        display.set_remote_cursor(40, 60)
        assert display._remote_cursor == (40, 60)  # noqa: SLF001
        display.clear_remote_cursor()
        assert display._remote_cursor is None  # noqa: SLF001
    finally:
        display.deleteLater()


def _display():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication([])
    from je_auto_control.gui.remote_desktop.frame_display import _FrameDisplay
    display = _FrameDisplay()
    display.resize(400, 300)
    display.set_image(QImage(400, 300, QImage.Format.Format_RGB32))
    sent = []
    for name in ("mouse_pressed", "mouse_released", "key_pressed", "key_released", "type_text",
                 "annotation_event"):
        getattr(display, name).connect(lambda *args, _name=name: sent.append((_name, *args)))
    return display, sent


def _mouse(kind, x, y, held=True):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    button = Qt.MouseButton.LeftButton
    return QMouseEvent(getattr(QEvent.Type, kind), QPointF(x, y), QPointF(x, y), button,
                       button if held else Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)


def test_a_button_let_go_outside_the_frame_is_released_on_the_host():
    """A drag that ended past the frame's edge sent no release: the host went on dragging."""
    display, sent = _display()
    try:
        display.mousePressEvent(_mouse("MouseButtonPress", 100, 100))
        display.mouseReleaseEvent(_mouse("MouseButtonRelease", 900, 120, held=False))
        assert sent[0] == ("mouse_pressed", 100, 100, "mouse_left")
        assert sent[1] == ("mouse_released", 399, 120, "mouse_left")
        display.mouseReleaseEvent(_mouse("MouseButtonRelease", 900, 120, held=False))     # nothing is held now
        assert len(sent) == 2
    finally:
        display.deleteLater()


def test_a_pen_stroke_let_go_outside_the_frame_ends():
    display, sent = _display()
    try:
        display.set_pen_mode(True)
        display.mousePressEvent(_mouse("MouseButtonPress", 10, 10))
        display.mouseReleaseEvent(_mouse("MouseButtonRelease", -50, 10, held=False))
        assert sent == [("annotation_event", "begin", 10, 10), ("annotation_event", "end", 0, 10)]
        assert display._pen_drawing is False
    finally:
        display.deleteLater()


def _key(kind, key, text="", modifier="NoModifier"):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    return QKeyEvent(getattr(QEvent.Type, kind), key, getattr(Qt.KeyboardModifier, modifier), text)


def test_a_shortcut_reaches_the_host_as_its_key_not_as_a_control_character():
    """Ctrl+C arrived as typed text ``\\x03``, which no application takes for Copy."""
    from PySide6.QtCore import Qt
    display, sent = _display()
    try:
        display.keyPressEvent(_key("KeyPress", Qt.Key.Key_Control, modifier="ControlModifier"))
        display.keyPressEvent(_key("KeyPress", Qt.Key.Key_C, "\x03", "ControlModifier"))
        display.keyReleaseEvent(_key("KeyRelease", Qt.Key.Key_C, "\x03", "ControlModifier"))
        display.keyPressEvent(_key("KeyPress", Qt.Key.Key_A, "A", "ShiftModifier"))      # text is kept as typed
        assert sent == [("key_pressed", "control"), ("key_pressed", "c"), ("key_released", "c"),
                        ("key_pressed", "A")]
    finally:
        display.deleteLater()


def test_keys_held_when_the_focus_leaves_are_released_on_the_host():
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QFocusEvent
    display, sent = _display()
    try:
        display.keyPressEvent(_key("KeyPress", Qt.Key.Key_Alt, modifier="AltModifier"))
        display.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))          # Alt+Tab: the release goes elsewhere
        display.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
        assert sent == [("key_pressed", "menu"), ("key_released", "menu")]
    finally:
        display.deleteLater()
