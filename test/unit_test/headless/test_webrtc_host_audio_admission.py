"""The host plays a viewer's Opus audio only for an approved viewer with audio allowed.

The PCM mic channel and the viewer-video track already checked authentication
per message or frame; the Opus track started playing as soon as it arrived, so
a peer still waiting on the Accept/Reject prompt -- or one the operator had
denied audio -- was heard on the host's speakers.
"""
import types

from je_auto_control.utils.remote_desktop.webrtc_host import WebRTCDesktopHost


class _Owners:
    def __init__(self) -> None:
        self.started = None

    def require_available(self, _name) -> None:
        return None

    def create(self, _name, _factory):
        return _Receiver()

    def activate(self, _name, start, _receiver) -> None:
        self.started = start


class _Receiver:
    def __init__(self) -> None:
        self.admit = None

    def consume(self, _track, *, admit=None) -> None:
        self.admit = admit


def _host(*, authenticated: bool, allow_audio: bool) -> WebRTCDesktopHost:
    host = WebRTCDesktopHost.__new__(WebRTCDesktopHost)
    host._authenticated = authenticated
    host._permissions = types.SimpleNamespace(allow_audio=allow_audio)
    host._media_owners = _Owners()
    host._opus_audio_receiver = None
    return host


def test_opus_receive_is_started_with_the_audio_admission_gate():
    host = _host(authenticated=False, allow_audio=True)
    host._start_opus_audio_receive(object())
    host._media_owners.started()
    admit = host._opus_audio_receiver.admit
    assert admit is not None
    assert admit() is False
    host._authenticated = True
    assert admit() is True
    host._permissions.allow_audio = False
    assert admit() is False


def test_audio_admission_needs_both_approval_and_allow_audio():
    for authenticated, allow_audio in ((False, False), (False, True), (True, False)):
        assert _host(authenticated=authenticated, allow_audio=allow_audio)._audio_admitted() is False
    assert _host(authenticated=True, allow_audio=True)._audio_admitted() is True
