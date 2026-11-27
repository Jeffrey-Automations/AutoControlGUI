"""The Win32 message module has to be importable, and must not edit ctypes.

Both of these were found by the typing contract rather than by anything that
ran: ``window_message`` imported a name its source module does not export, so
the module raised ``ImportError`` on every Windows machine and nothing in the
shipping path noticed because only a manual test imports it. And
``win32_ctype_input`` wrote ``ULONG_PTR`` into the standard library's own
``ctypes.wintypes`` namespace, which no code in this package ever read back —
so the only thing that assignment could do was answer for someone else's
``hasattr(wintypes, "ULONG_PTR")``.
"""
import ctypes
import sys
from ctypes import wintypes

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform not in ("win32", "cygwin", "msys"),
    reason="Windows input backend modules only import on Windows.",
)


def test_window_message_module_imports():
    """It used to raise ImportError before any of its functions were reachable."""
    from je_auto_control.windows.message import window_message

    for name in ("send_message_to_window", "send_message_to_window_hwnd",
                 "post_message_to_window", "post_message_to_window_hwnd"):
        assert callable(getattr(window_message, name))
    assert window_message.messages["WM_CLOSE"] == 0x0010


def test_window_lookup_goes_through_the_prototyped_helper():
    """The helper it calls is the one that declares HWND-width argtypes.

    ``FindWindowW`` off a raw handle defaults to ``c_int``, which truncates a
    64-bit HWND; ``get_one_window_hwnd`` sets the prototype first.
    """
    from je_auto_control.windows.message import window_message
    from je_auto_control.windows.window import windows_window_manage

    assert window_message.get_one_window_hwnd is (
        windows_window_manage.get_one_window_hwnd)
    missing = "je_auto_control window that does not exist 0f3a"
    assert windows_window_manage.get_one_window_hwnd(None, missing) == 0


def test_importing_the_input_module_leaves_ctypes_alone():
    """Importing a backend must not add names to a standard library module."""
    import je_auto_control.windows.core.utils.win32_ctype_input  # noqa: F401  # reason: imported for its side effects, which is what this asserts about

    assert not hasattr(wintypes, "ULONG_PTR")
    assert not hasattr(ctypes.wintypes, "ULONG_PTR")


_WM_APP = 0x8000
_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


def _own_user32():
    """A private user32 with prototypes for the calls that build the test's own window."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user.DefWindowProcW.restype = _LRESULT
    user.RegisterClassW.argtypes = (ctypes.POINTER(_WNDCLASSW),)
    user.RegisterClassW.restype = wintypes.ATOM
    user.UnregisterClassW.argtypes = (wintypes.LPCWSTR, wintypes.HINSTANCE)
    user.CreateWindowExW.argtypes = (
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
    user.CreateWindowExW.restype = wintypes.HWND
    user.DestroyWindow.argtypes = (wintypes.HWND,)
    return user


@pytest.fixture
def own_message_window():
    """A message-only window this test creates; its procedure echoes WM_APP's lParam.

    Message-only windows (parent ``HWND_MESSAGE``) are invisible and receive no
    broadcasts, so nothing outside this process sees the messages.
    """
    user = _own_user32()
    seen = []

    def procedure(hwnd, message, wparam, lparam):
        if message == _WM_APP:
            seen.append(wparam)
            return lparam
        return user.DefWindowProcW(hwnd, message, wparam, lparam)

    callback = _WNDPROC(procedure)
    class_name = f"je_auto_control_window_message_test_{id(callback):x}"
    window_class = _WNDCLASSW(lpfnWndProc=callback, lpszClassName=class_name)
    assert user.RegisterClassW(ctypes.byref(window_class)), ctypes.get_last_error()
    hwnd_message = wintypes.HWND(-3)
    hwnd = user.CreateWindowExW(0, class_name, None, 0, 0, 0, 0, 0, hwnd_message, None, None, None)
    try:
        assert hwnd, ctypes.get_last_error()
        yield hwnd, seen
    finally:
        if hwnd:
            user.DestroyWindow(hwnd)
        user.UnregisterClassW(class_name, None)


@pytest.mark.skipif(sys.maxsize <= 2 ** 32, reason="the high-bit round trip needs a 64-bit process")
def test_send_message_round_trips_pointer_width_values(own_message_window):
    """WPARAM, LPARAM and LRESULT keep their high 32 bits on Win64.

    Without prototypes ctypes passes each argument as a C ``int`` (a value over
    32 bits does not even convert) and reads the result as a 4-byte ``long``.
    """
    from je_auto_control.windows.message import window_message

    hwnd, seen = own_message_window
    wparam = 0xFEDC_BA98_7654_3210
    lparam = -0x0123_4567_89AB_CDEF
    returned_hwnd, result = window_message.send_message_to_window_hwnd(hwnd, _WM_APP, wparam, lparam)
    assert returned_hwnd == hwnd
    assert seen == [wparam]
    assert result == lparam


def test_message_prototypes_live_on_a_private_user32():
    """The prototypes do not leak onto the user32 the input backend shares."""
    from je_auto_control.windows.core.utils import win32_ctype_input
    from je_auto_control.windows.message import window_message

    word = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    assert tuple(window_message.SendMessageW.argtypes) == word
    assert tuple(window_message.PostMessageW.argtypes) == word
    assert window_message.SendMessageW.restype is ctypes.c_ssize_t
    assert window_message.PostMessageW.restype is wintypes.BOOL
    assert window_message.SendMessageW is not win32_ctype_input.user32.SendMessageW
    assert window_message.PostMessageW is not win32_ctype_input.user32.PostMessageW
