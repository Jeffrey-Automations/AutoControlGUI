"""Start and stop of the Windows record hook thread. No real hooks, no real input.

``start`` waited five seconds for the hook thread and ignored a timeout; if
the worker had not set its thread id yet, ``stop`` returned at once and the
worker went on to install the hooks and pump messages for the life of the
process. The result of posting ``WM_QUIT`` was not checked, and the events
were handed over while the thread could still be appending to them. The
native calls are replaced by a fake whose start can be held back.
"""
import sys
import threading

import pytest

if not sys.platform.startswith("win"):        # pragma: no cover
    pytest.skip("Windows recorder", allow_module_level=True)

from je_auto_control.utils.exception.exceptions import AutoControlRecordException  # noqa: E402
from je_auto_control.windows.record import win32_input_hook  # noqa: E402

_LATE_EVENT = {"op": "key_up", "vk": 65, "time": 1.0}


class _FakeHook(win32_input_hook.Win32InputHook):
    """Every native step replaced; ``release`` holds the worker before it has a thread id."""

    start_timeout = 0.05
    stop_timeout = 2.0

    def __init__(self, release: threading.Event, *, post_succeeds: bool = True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.release = release
        self.post_succeeds = post_succeeds
        self.pumping, self.quit, self.unhooked = threading.Event(), threading.Event(), threading.Event()
        self.posts = 0

    def _open_queue(self, user32) -> None:
        assert self.release.wait(5)
        self._thread_id = 1

    def _install(self, user32) -> None:
        self._hooks.append(object())

    def _pump(self, user32) -> None:
        self.pumping.set()
        self.on_pump()
        assert self.quit.wait(5)            # GetMessageW returns 0 for WM_QUIT
        self.events.append(dict(_LATE_EVENT))  # input queued ahead of the quit

    def on_pump(self) -> None:
        """What the hook callbacks do while the pump runs."""

    def _unhook(self, user32) -> None:
        self._hooks = []
        self.unhooked.set()

    def _post_quit(self) -> bool:
        self.posts += 1
        if self.post_succeeds:
            self.quit.set()
        return self.post_succeeds


@pytest.fixture(autouse=True)
def _no_native_user32(monkeypatch):
    monkeypatch.setattr(win32_input_hook, "_user32", object)


def _started(**kwargs) -> _FakeHook:
    release = threading.Event()
    release.set()
    hook = _FakeHook(release, **kwargs)
    hook.start()
    assert hook.pumping.wait(5)
    return hook


def test_a_start_that_times_out_raises_and_the_late_worker_never_pumps():
    release = threading.Event()
    hook = _FakeHook(release)
    with pytest.raises(AutoControlRecordException, match="did not start"):
        hook.start()
    release.set()                       # the worker gets its thread id only now
    assert hook.stop() == []
    assert not hook._thread.is_alive()
    assert not hook.pumping.is_set()
    assert hook.unhooked.is_set()


def test_stop_hands_over_the_events_only_after_the_thread_has_exited():
    hook = _started()
    events = hook.stop()
    assert not hook._thread.is_alive()
    assert hook.posts == 1
    assert events == [_LATE_EVENT]
    assert hook.unhooked.is_set()


def test_a_quit_that_cannot_be_posted_is_an_error_and_hands_over_nothing():
    hook = _started(post_succeeds=False)
    hook.stop_timeout = 0.05
    try:
        with pytest.raises(AutoControlRecordException, match="WM_QUIT"):
            hook.stop()
        assert hook._thread.is_alive()
    finally:
        hook.quit.set()
        hook._thread.join(5)


def test_the_event_cap_stops_the_hook_from_its_own_thread():
    hook = _FakeHook(threading.Event(), max_events=0)
    hook.release.set()
    hook.on_pump = lambda: hook._put({"op": "key_down", "vk": 65})
    hook.start()
    hook._thread.join(5)                # the cap posted the quit itself
    assert not hook._thread.is_alive()
    assert hook.stop() == [_LATE_EVENT]


def _presence_hook(**kwargs):
    """The agent's presence hook, which builds on this one, over the same fakes."""
    from je_auto_control.utils.agent_runtime import activity_windows
    presence = type(activity_windows._listener(lambda: None))

    class _FakePresence(_FakeHook, presence):
        stop_timeout = _FakeHook.stop_timeout    # not PresenceHook's own second

    release = threading.Event()
    release.set()
    hook = _FakePresence(release, **kwargs)
    hook.start()
    assert hook.pumping.wait(5)
    return hook


def test_the_presence_hook_retires_through_the_same_stop():
    hook = _presence_hook()
    assert hook.alive()
    assert hook.stop() == []
    assert not hook._thread.is_alive()


def test_a_presence_hook_that_does_not_retire_is_an_agent_error():
    from je_auto_control.utils.agent_runtime.errors import AgentTaskError
    hook = _presence_hook(post_succeeds=False)
    hook.stop_timeout = 0.05
    try:
        with pytest.raises(AgentTaskError, match="not retired"):
            hook.stop()
    finally:
        hook.quit.set()
        hook._thread.join(5)
