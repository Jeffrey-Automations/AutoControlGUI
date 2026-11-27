"""A stop ends the wait for a VLM request; the request itself finishes in the background. No Qt, no network."""
import threading
import time

import pytest

from je_auto_control.utils.executor.run_control import ExecutionStopped, stoppable_run


class BlockedBackend:
    """A configured backend whose request does not return until the test lets it."""

    name, available = "blocked", True

    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()

    def resolve_model(self, model):
        return model

    def locate(self, image, description, model=None):
        self.entered.set()
        self.release.wait(10)
        return (1, 1)


def _stopped_while_blocked(call):
    backend = BlockedBackend()
    started = time.monotonic()
    try:
        with pytest.raises(ExecutionStopped):
            with stoppable_run() as token:
                threading.Thread(target=lambda: backend.entered.wait(5) and token.stop(), daemon=True).start()
                call(backend)
        assert backend.entered.is_set()
        assert time.monotonic() - started < 5
    finally:
        backend.release.set()


def test_the_desktop_vlm_locator_stops_waiting_for_the_model(monkeypatch):
    from je_auto_control.utils.vision import vlm_api
    monkeypatch.setattr(vlm_api, "capture_with_geometry", lambda capture, region: (b"png", None))
    monkeypatch.setattr(vlm_api, "_to_screen", lambda coords, image, region: coords)
    _stopped_while_blocked(lambda backend: vlm_api.locate_by_description("the OK button", backend=backend))


def test_the_device_frame_vlm_locator_stops_waiting_for_the_model(monkeypatch):
    from je_auto_control.wrapper import device_frame
    frame = object.__new__(device_frame.DeviceFrame)
    monkeypatch.setattr(device_frame.DeviceFrame, "png", lambda self: b"png")
    monkeypatch.setattr(device_frame.DeviceFrame, "pixel_size", property(lambda self: (10, 10)), raising=False)
    _stopped_while_blocked(lambda backend: frame.locate_description("the OK button", backend=backend))


def test_outside_a_run_the_request_is_a_plain_call(monkeypatch):
    from je_auto_control.utils.vision import vlm_api
    backend = BlockedBackend()
    backend.release.set()
    monkeypatch.setattr(vlm_api, "capture_with_geometry", lambda capture, region: (b"png", None))
    monkeypatch.setattr(vlm_api, "_to_screen", lambda coords, image, region: coords)
    assert vlm_api.locate_by_description("x", backend=backend) == (1, 1)
