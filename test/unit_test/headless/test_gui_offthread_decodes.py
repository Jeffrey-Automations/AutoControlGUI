"""Images the views decoded in their slots are decoded on a thread of each view's own (offscreen Qt, fakes).

The remote screens decoded every JPEG frame on the GUI thread, as did the host
preview, the agent observation preview and the template candidate thumbnails.
Each decode here is replaced by one that waits on a gate, so a test sees the
slot return first, the image arrive later, a newer source replace an older one,
and an image of a session or frame that changed meanwhile -- or of a view that
was disposed -- never painted. Nothing reads the screen or shows a window.
"""
import base64
import io
import os
import threading
import time
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QBuffer, QIODevice, QObject  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from headless._qt_settle import deleting, pump_until  # noqa: E402
from je_auto_control.gui import _latest_decoder  # noqa: E402
from je_auto_control.gui._latest_decoder import LatestDecoder, decode_jpeg  # noqa: E402
from je_auto_control.gui.remote_desktop import connection_screen, host_panel, viewer_panel  # noqa: E402
from je_auto_control.gui.tab_task_controller import task_controller  # noqa: E402
from je_auto_control.utils.remote_desktop.registry import registry  # noqa: E402

_WAIT = 10.0


@pytest.fixture(autouse=True)
def qapp(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(registry, "_viewer", None)
    monkeypatch.setattr(registry, "_ws_viewer", None)
    monkeypatch.setattr(registry, "_host", None)
    with deleting(connection_screen.QuickConnectScreen, viewer_panel._ViewerPanel, host_panel._HostPanel):
        yield app


class _Gate:
    """A decode that blocks until released, remembers where it ran, then decodes for real."""

    def __init__(self, decode=decode_jpeg) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list = []
        self.threads: list = []
        self._decode = decode

    def __call__(self, source):
        self.calls.append(source)
        self.threads.append(threading.get_ident())
        self.entered.set()
        self.release.wait(_WAIT)
        return self._decode(source)

    def off_gui_thread(self) -> bool:
        return bool(self.threads) and all(ident != threading.get_ident() for ident in self.threads)


class _Sink(QObject):
    """What a view's slots would be: records each delivery on the GUI thread."""

    def __init__(self) -> None:
        super().__init__()
        self.decoded: list = []
        self.failed: list = []

    def on_decoded(self, tag, image) -> None:
        self.decoded.append((tag, image))

    def on_failed(self, tag, error) -> None:
        self.failed.append((tag, error))


def _jpeg(color: int = 0x336699) -> bytes:
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(color)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPEG")
    return bytes(buffer.data())


def _returns_at_once(slot, *args) -> None:
    started = time.monotonic()
    slot(*args)
    assert time.monotonic() - started < 5.0, "the slot held the GUI thread"


def _idle(before: int) -> bool:
    return pump_until(lambda: task_controller().active_count() == before)


# --- the decoder ----------------------------------------------------------------------------------------------

def test_the_newest_source_replaces_one_not_yet_decoded():
    sink, gate = _Sink(), _Gate()
    decoder = LatestDecoder(sink, gate, sink.on_decoded)
    decoder.submit(_jpeg(), 1)
    assert gate.entered.wait(_WAIT)
    decoder.submit(_jpeg(0x00FF00), 2)                  # replaced by the next one before it is decoded
    decoder.submit(_jpeg(0xFF0000), 3)
    assert decoder.busy
    gate.release.set()
    assert pump_until(lambda: len(sink.decoded) == 2 and not decoder.busy)
    assert [tag for tag, _image in sink.decoded] == [1, 3]
    assert len(gate.calls) == 2
    assert gate.off_gui_thread()
    assert not sink.decoded[1][1].isNull()
    decoder.stop()


def test_the_next_decode_waits_until_the_gui_thread_took_the_last_image():
    sink, calls = _Sink(), []
    decoded = threading.Event()

    def decode(source):
        calls.append(source)
        decoded.set()
        return QImage()

    decoder = LatestDecoder(sink, decode, sink.on_decoded)
    decoder.submit(b"a", 1)
    assert decoded.wait(_WAIT)
    decoder.submit(b"b", 2)
    time.sleep(0.2)                                     # no event loop: the first image was not taken yet
    assert calls == [b"a"]
    assert pump_until(lambda: len(sink.decoded) == 2)
    assert calls == [b"a", b"b"]
    decoder.stop()


def test_a_failed_decode_reaches_on_failed_and_the_next_one_still_decodes():
    sink = _Sink()

    def decode(source):
        if source == b"bad":
            raise ValueError("not an image")
        return decode_jpeg(source)

    decoder = LatestDecoder(sink, decode, sink.on_decoded, sink.on_failed)
    decoder.submit(b"bad", 1)
    assert pump_until(lambda: bool(sink.failed))
    decoder.submit(_jpeg(), 2)
    assert pump_until(lambda: bool(sink.decoded))
    assert isinstance(sink.failed[0][1], ValueError) and sink.failed[0][0] == 1
    assert sink.decoded[0][0] == 2
    decoder.stop()


def test_stop_drops_a_decode_still_out_and_ends_the_thread():
    before = task_controller().active_count()
    sink, gate = _Sink(), _Gate()
    decoder = LatestDecoder(sink, gate, sink.on_decoded)
    decoder.submit(_jpeg(), 1)
    assert gate.entered.wait(_WAIT)
    decoder.stop()
    decoder.submit(_jpeg(), 2)                          # after stop: refused
    gate.release.set()
    assert _idle(before)
    assert sink.decoded == []
    assert len(gate.calls) == 1


def test_the_thread_ends_when_idle_and_starts_again_for_the_next_source(monkeypatch):
    before = task_controller().active_count()
    sink = _Sink()
    decoder = LatestDecoder(sink, decode_jpeg, sink.on_decoded, idle_s=0.05)
    decoder.submit(_jpeg(), 1)
    assert pump_until(lambda: len(sink.decoded) == 1)
    assert _idle(before)                                # nothing more to decode: no thread is left
    decoder.submit(_jpeg(), 2)
    assert pump_until(lambda: len(sink.decoded) == 2)
    decoder.stop()
    assert _idle(before)
    assert _latest_decoder.IDLE_S > 0


# --- the remote screens ----------------------------------------------------------------------------------------

_VIEWS = [
    pytest.param(connection_screen, "QuickConnectScreen", "_on_frame", "_pending_image", id="quick_connect"),
    pytest.param(viewer_panel, "_ViewerPanel", "_on_frame_main", "_early_frame", id="viewer_panel"),
]


@pytest.mark.parametrize("module, class_name, slot, shown", _VIEWS)
def test_a_remote_frame_is_decoded_off_the_gui_thread(monkeypatch, module, class_name, slot, shown):
    gate = _Gate()
    monkeypatch.setattr(module, "decode_jpeg", gate)
    view = getattr(module, class_name)()
    _returns_at_once(getattr(view, slot), _jpeg())
    assert gate.entered.wait(_WAIT)
    assert getattr(view, shown) is None
    gate.release.set()
    assert pump_until(lambda: getattr(view, shown) is not None)
    assert gate.off_gui_thread()
    view.dispose()


@pytest.mark.parametrize("module, class_name, slot, shown", _VIEWS)
def test_a_frame_of_a_session_closed_while_it_decoded_is_dropped(monkeypatch, module, class_name, slot, shown):
    gate = _Gate()
    monkeypatch.setattr(module, "decode_jpeg", gate)
    view = getattr(module, class_name)()
    getattr(view, slot)(_jpeg())
    assert gate.entered.wait(_WAIT)
    view._disconnect()                                  # the session number moves on
    gate.release.set()
    assert pump_until(lambda: not view._decoder.busy)
    assert getattr(view, shown) is None
    view.dispose()


@pytest.mark.parametrize("module, class_name, slot, shown", _VIEWS)
def test_dispose_drops_the_frame_still_decoding(monkeypatch, module, class_name, slot, shown):
    before = task_controller().active_count()
    gate = _Gate()
    monkeypatch.setattr(module, "decode_jpeg", gate)
    view = getattr(module, class_name)()
    getattr(view, slot)(_jpeg())
    assert gate.entered.wait(_WAIT)
    view.dispose()
    gate.release.set()
    assert _idle(before)
    assert getattr(view, shown) is None


class _Host:
    is_running, port, connected_clients, host_id = True, 4321, 0, "123456789"

    def __init__(self, frame: bytes) -> None:
        self.frame = frame

    def latest_frame(self):
        return self.frame


def _preview_panel(monkeypatch, gate):
    monkeypatch.setattr(host_panel, "decode_jpeg", gate)
    panel = host_panel._HostPanel()
    panel._preview_timer.stop()                         # each test drives the preview itself
    monkeypatch.setattr(panel, "isVisible", lambda: True)
    return panel


def test_the_host_preview_decodes_off_the_gui_thread_and_once_per_frame(monkeypatch):
    gate = _Gate()
    panel = _preview_panel(monkeypatch, gate)
    monkeypatch.setattr(registry, "_host", _Host(_jpeg()))
    _returns_at_once(panel._refresh_preview)
    assert gate.entered.wait(_WAIT)
    assert not panel._preview.has_image()
    gate.release.set()
    assert pump_until(panel._preview.has_image)
    assert gate.off_gui_thread()
    panel._refresh_preview()                            # the same frame: nothing new to decode
    assert pump_until(lambda: not panel._preview_decoder.busy)
    assert len(gate.calls) == 1
    panel.dispose()


def test_a_preview_decoding_when_the_host_stops_is_not_painted(monkeypatch):
    gate = _Gate()
    panel = _preview_panel(monkeypatch, gate)
    host = _Host(_jpeg())
    monkeypatch.setattr(registry, "_host", host)
    panel._refresh_preview()
    assert gate.entered.wait(_WAIT)
    host.is_running = False
    panel._refresh_preview()                            # clears the preview
    gate.release.set()
    assert pump_until(lambda: not panel._preview_decoder.busy)
    assert not panel._preview.has_image()
    panel.dispose()


def test_host_panel_dispose_drops_the_preview_still_decoding(monkeypatch):
    before = task_controller().active_count()
    gate = _Gate()
    panel = _preview_panel(monkeypatch, gate)
    monkeypatch.setattr(registry, "_host", _Host(_jpeg()))
    panel._refresh_preview()
    assert gate.entered.wait(_WAIT)
    panel.dispose()
    gate.release.set()
    assert _idle(before)
    assert not panel._preview.has_image()


# --- the agent observation preview -----------------------------------------------------------------------------

def _observation(frame: str = "frame-a") -> dict:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (20, 10), "black").save(buffer, format="JPEG")
    return {"observation_id": frame, "data": {"elements": [], "image": {
        "format": "jpeg", "redacted_by": "strict", "image_size": [20, 10],
        "data": base64.b64encode(buffer.getvalue()).decode("ascii")}}}


def _observation_view(monkeypatch, gate):
    from je_auto_control.gui import agent_observation_view as module
    gate._decode = module._decode_observation_image
    monkeypatch.setattr(module, "_decode_observation_image", gate)
    return module.AgentObservationView()


def test_the_observation_image_is_checked_and_decoded_off_the_gui_thread(monkeypatch):
    gate = _Gate()
    view = _observation_view(monkeypatch, gate)
    _returns_at_once(view.present, _observation())
    assert gate.entered.wait(_WAIT)
    assert view._image.pixmap().isNull()
    assert view._image.text()                           # the loading text while it decodes
    gate.release.set()
    assert pump_until(lambda: not view._image.pixmap().isNull())
    assert (view._image.width(), view._image.height()) == (20, 10)
    assert gate.off_gui_thread()
    view.dispose()
    view.deleteLater()


def test_an_observation_replaced_or_disposed_while_it_decoded_is_not_painted(monkeypatch):
    before = task_controller().active_count()
    gate = _Gate()
    view = _observation_view(monkeypatch, gate)
    view.present(_observation())
    assert gate.entered.wait(_WAIT)
    view.clear()                                        # the task changed
    gate.release.set()
    assert pump_until(lambda: not view._decoder.busy)
    assert view._image.pixmap().isNull()
    gate.entered.clear()
    gate.release.clear()
    view.present(_observation("frame-b"))
    assert gate.entered.wait(_WAIT)
    view.dispose()
    gate.release.set()
    assert _idle(before)
    assert view._image.pixmap().isNull()
    view.deleteLater()


def test_an_untrusted_observation_image_is_reported_in_the_view():
    from je_auto_control.gui.agent_observation_view import AgentObservationView
    view = AgentObservationView()
    observation = _observation()
    observation["data"]["image"]["image_size"] = [2000, 1000]
    view.present(observation)
    assert pump_until(lambda: bool(view._notice.text()))
    assert "geometry" in view._notice.text()
    assert view._image.pixmap().isNull()
    view.dispose()
    view.deleteLater()


# --- the template candidate thumbnails -------------------------------------------------------------------------

def _png() -> bytes:
    image = QImage(16, 8, QImage.Format.Format_RGB32)
    image.fill(0x112233)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def _candidate_panel(monkeypatch, gate):
    from je_auto_control.gui import template_candidate_panel as module
    gate._decode = module._decode_thumbnails
    monkeypatch.setattr(module, "_decode_thumbnails", gate)
    return module.TemplateCandidatePanel()


def _preview_outcome():
    state = types.SimpleNamespace(template_path="t.png", threshold=0.9, revision="r" * 64)
    return types.SimpleNamespace(preview=types.SimpleNamespace(state=state, original_png=_png(),
                                                               candidate_png=_png()))


def test_the_candidate_thumbnails_are_decoded_off_the_gui_thread(monkeypatch):
    gate = _Gate()
    panel = _candidate_panel(monkeypatch, gate)
    _returns_at_once(panel._show_preview, _preview_outcome())
    assert gate.entered.wait(_WAIT)
    assert panel._original.pixmap().isNull() and panel._original.text()
    gate.release.set()
    assert pump_until(lambda: not panel._replacement.pixmap().isNull())
    assert not panel._original.pixmap().isNull()
    assert gate.off_gui_thread()
    panel.dispose()
    panel.deleteLater()


def test_thumbnails_of_inputs_changed_or_a_disposed_panel_are_not_painted(monkeypatch):
    before = task_controller().active_count()
    gate = _Gate()
    panel = _candidate_panel(monkeypatch, gate)
    panel._show_preview(_preview_outcome())
    assert gate.entered.wait(_WAIT)
    panel._bundle.setText("another.json")               # the review no longer applies
    gate.release.set()
    assert pump_until(lambda: not panel._decoder.busy)
    assert panel._original.pixmap().isNull()
    gate.entered.clear()
    gate.release.clear()
    panel._show_preview(_preview_outcome())
    assert gate.entered.wait(_WAIT)
    panel.dispose()
    gate.release.set()
    assert _idle(before)
    assert panel._original.pixmap().isNull()
    panel.deleteLater()
