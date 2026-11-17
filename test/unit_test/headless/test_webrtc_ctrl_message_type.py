"""A control message whose ``type`` is not a string is ignored, on the host and the viewer.

``{"type": []}`` reached a dict lookup and raised ``TypeError: unhashable type``
from inside the data channel's message callback.
"""
import json
import threading

import pytest

pytest.importorskip("aiortc")

from je_auto_control.utils.remote_desktop.webrtc_host import WebRTCDesktopHost  # noqa: E402
from je_auto_control.utils.remote_desktop.webrtc_viewer import WebRTCDesktopViewer  # noqa: E402

_ODD_TYPES = ([], {}, 7, None)


def _bare(cls: type, **attributes: object) -> object:
    """The class without its constructor: only what ``_handle_ctrl_message`` reads."""
    instance = object.__new__(cls)
    instance._closed = threading.Event()
    for name, value in attributes.items():
        setattr(instance, name, value)
    return instance


@pytest.mark.parametrize("odd", _ODD_TYPES)
def test_the_host_ignores_a_non_string_type(odd):
    host = _bare(WebRTCDesktopHost, _authenticated=True)
    host._handle_ctrl_message(json.dumps({"type": odd}))


@pytest.mark.parametrize("odd", _ODD_TYPES)
def test_the_host_ignores_a_non_string_type_before_auth(odd):
    host = _bare(WebRTCDesktopHost, _authenticated=False)
    host._handle_ctrl_message(json.dumps({"type": odd}))


@pytest.mark.parametrize("odd", _ODD_TYPES)
def test_the_viewer_ignores_a_non_string_type(odd):
    viewer = _bare(WebRTCDesktopViewer)
    viewer._handle_ctrl_message(json.dumps({"type": odd}))


def test_a_string_type_still_reaches_its_handler():
    seen = []
    viewer = _bare(WebRTCDesktopViewer)
    viewer._handle_read_only_msg = seen.append
    viewer._handle_ctrl_message(json.dumps({"type": "read_only", "value": True}))
    assert seen == [{"type": "read_only", "value": True}]
