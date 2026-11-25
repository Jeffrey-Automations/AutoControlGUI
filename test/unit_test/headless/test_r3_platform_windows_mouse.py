"""Round-3 platform regression tests: Windows mouse backend.

Headless — no real mouse/keyboard input is dispatched. The backend layer
(``_send_stroke`` / ``PostMessageW``) is monkeypatched or exercised only
through pure helpers, so nothing touches the OS input APIs.

Covers audit findings:
* #1 ``mouse_keys_table`` must be built from the *selected* backend.
* #2 Interception ``scroll`` must scale a notch count by ``WHEEL_DELTA``.
* #7 ``send_mouse_event_to_window`` must post WM_* messages, not the
  SendInput button tuple.
* #8 ``SendInput.argtypes`` typo (``arg_types``) must be corrected.
"""
import ctypes
import sys
import types
from ctypes import wintypes

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform not in ("win32", "cygwin", "msys"),
    reason="Windows input backend modules only import on Windows.",
)


def test_finding1_mouse_keys_table_built_from_selected_backend():
    """The table reflects the selected backend's flag tuples, not the
    import-time SendInput globals."""
    from je_auto_control.wrapper import _platform_windows as pw
    from je_auto_control.windows.interception import mouse as interception_mouse
    from je_auto_control.windows.mouse import win32_ctype_mouse_control as sendinput_mouse

    table = pw._build_mouse_keys_table(interception_mouse)
    # Built from the module handed in — Interception constants, not SendInput.
    assert table["mouse_left"] == interception_mouse.win32_mouse_left
    assert table["mouse_right"] == interception_mouse.win32_mouse_right
    # Interception bitmasks differ from SendInput dwFlags: proves the
    # distinction the bug erased.
    assert interception_mouse.win32_mouse_left != sendinput_mouse.win32_mouse_left
    assert table["mouse_left"] != sendinput_mouse.win32_mouse_left
    # The live module table matches whatever backend it actually selected.
    assert pw.mouse_keys_table["mouse_left"] == pw.mouse.win32_mouse_left


def test_finding2_interception_scroll_scales_by_wheel_delta(monkeypatch):
    """One notch must move one notch: rolling == value * 120."""
    from je_auto_control.windows.interception import mouse as interception_mouse

    captured = {}

    def _fake_send(state, *, flags=0, x=0, y=0, rolling=0):
        captured["state"] = state
        captured["rolling"] = rolling

    monkeypatch.setattr(interception_mouse, "_send_stroke", _fake_send)
    interception_mouse.scroll(3)
    assert captured["state"] == interception_mouse.MOUSE_WHEEL
    assert captured["rolling"] == 3 * 120


def test_finding7_window_message_translation_not_raw_tuple():
    """The window path resolves a button tuple into integer WM_* messages."""
    from je_auto_control.utils.exception.exceptions import AutoControlException
    from je_auto_control.windows.mouse import win32_ctype_mouse_control as sendinput_mouse

    down, up = sendinput_mouse._resolve_window_messages(sendinput_mouse.win32_mouse_left)
    assert down == (sendinput_mouse.WM_LBUTTONDOWN, sendinput_mouse.MK_LBUTTON)
    assert up == (sendinput_mouse.WM_LBUTTONUP, 0)
    # A window message is an int — never the SendInput dwFlags tuple.
    assert isinstance(down[0], int)
    assert down[0] != sendinput_mouse.win32_mouse_left

    right_down, _ = sendinput_mouse._resolve_window_messages(sendinput_mouse.win32_mouse_right)
    assert right_down[0] == sendinput_mouse.WM_RBUTTONDOWN

    with pytest.raises(AutoControlException):
        sendinput_mouse._resolve_window_messages((9, 9, 9))


def test_finding8_sendinput_argtypes_applied():
    """The ``argtypes`` (not ``arg_types``) attribute must be set."""
    from je_auto_control.windows.core.utils import win32_ctype_input as mod

    assert mod.user32.SendInput.argtypes == (wintypes.UINT, ctypes.c_void_p, ctypes.c_int)


def test_a_refused_cursor_move_is_an_error(monkeypatch):
    """A locked desktop refuses SetCursorPos; the move was reported done and the click went elsewhere."""
    from je_auto_control.utils.exception.exceptions import AutoControlMouseException
    from je_auto_control.windows.mouse import win32_ctype_mouse_control as mouse
    monkeypatch.setattr(mouse, "_set_cursor_pos", lambda x, y: 0)
    with pytest.raises(AutoControlMouseException):
        mouse.set_position(10, 20)
    monkeypatch.setattr(mouse, "_set_cursor_pos", lambda x, y: 1)
    mouse.set_position(10, 20)


def _sent_key_flags(monkeypatch, keycode):
    """The dwFlags of the press and the release the keyboard backend builds; nothing is sent."""
    from je_auto_control.windows.keyboard import win32_ctype_keyboard_control as keyboard
    flags = []
    monkeypatch.setattr(keyboard, "SendInput",
                        lambda count, pointer, size: flags.append(pointer._obj.ki.dwFlags))
    keyboard.press_key(keycode)
    keyboard.release_key(keycode)
    return flags


_EXTENDED, _KEY_UP = 0x0001, 0x0002


@pytest.mark.parametrize("keycode", [0x21, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E,
                                     0x5B, 0x5D, 0x6F, 0x90, 0xA3, 0xA5])
def test_extended_keys_are_sent_as_extended(monkeypatch, keycode):
    """Without the flag an arrow is the numeric keypad's: Shift+Left selected nothing with NumLock on."""
    assert _sent_key_flags(monkeypatch, keycode) == [_EXTENDED, _EXTENDED | _KEY_UP]


@pytest.mark.parametrize("keycode", [0x41, 0x0D, 0x10, 0x11, 0x64, 0xA0, 0xA2, 0xA4])
def test_ordinary_keys_are_not_sent_as_extended(monkeypatch, keycode):
    assert _sent_key_flags(monkeypatch, keycode) == [0, _KEY_UP]


def test_interception_sends_arrows_and_navigation_keys_with_their_prefix():
    """MapVirtualKeyW gives the arrows no 0xE0 prefix, so the driver was sent the keypad's keys."""
    from je_auto_control.windows.interception import _dll
    for keycode in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0xA3, 0x6F):
        assert _dll.vk_to_scancode(keycode)[1] is True, hex(keycode)
    # At the driver NumLock itself is the plain 0x45; E0 45 is no key at all.
    for keycode in (0x41, 0x64, 0x90, 0x0D):
        assert _dll.vk_to_scancode(keycode)[1] is False, hex(keycode)


def test_a_key_tapped_earlier_is_not_reported_as_held(monkeypatch):
    """GetAsyncKeyState's low bit means "since the last call": a released key read as pressed."""
    from je_auto_control.windows.core.utils import win32_keypress_check
    from je_auto_control.wrapper import auto_control_keyboard
    state = {"value": 0x0001}
    monkeypatch.setattr(win32_keypress_check.ctypes, "windll", types.SimpleNamespace(
        user32=types.SimpleNamespace(GetAsyncKeyState=lambda code: state["value"])))
    monkeypatch.setattr(auto_control_keyboard, "keyboard_check", win32_keypress_check)
    assert auto_control_keyboard.check_key_is_press(0x41) is False
    state["value"] = -32768          # the SHORT 0x8000, sign-extended
    assert auto_control_keyboard.check_key_is_press(0x41) is True
    # The panic key keeps the sticky bit: a tap shorter than its poll still counts.
    state["value"] = 0x0001
    assert win32_keypress_check.check_key_is_press(0x41) is True
