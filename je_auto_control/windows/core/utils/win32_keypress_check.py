import sys

from je_auto_control.utils.exception.exception_tags import windows_import_error_message
from je_auto_control.utils.exception.exceptions import AutoControlException

if sys.platform not in ["win32", "cygwin", "msys"]:
    raise AutoControlException(windows_import_error_message)

import ctypes


def is_key_down(keycode: int) -> bool:
    """Whether the key is down right now.

    The high bit only: the low one says the key was pressed since some
    earlier call, so a key tapped a minute ago read as held.
    :func:`check_key_is_press` keeps both for the panic-key watcher, where a
    tap shorter than its polling interval has to count.
    """
    state: int = ctypes.windll.user32.GetAsyncKeyState(  # type: ignore[attr-defined]  # reason: win32-only ctypes
        int(keycode))
    return bool(state & 0x8000)


def check_key_is_press(keycode: int | str) -> bool:
    if isinstance(keycode, int):
        temp: int = ctypes.windll.user32.GetAsyncKeyState(  # type: ignore[attr-defined]  # reason: win32-only ctypes
            keycode)
    else:
        temp = ctypes.windll.user32.GetAsyncKeyState(  # type: ignore[attr-defined]  # reason: win32-only ctypes
            ord(keycode))
    if temp != 0:
        return True
    return False
