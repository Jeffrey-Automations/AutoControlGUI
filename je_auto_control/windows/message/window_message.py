import ctypes
from ctypes import wintypes
from typing import Any

from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.windows.window.windows_window_manage import get_one_window_hwnd

# A private user32: the prototypes below must not change the function objects
# other modules get from their own (shared) user32 handle.
_user32: Any = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]  # reason: win32-only ctypes
# WPARAM, LPARAM and LRESULT are pointer-sized; without prototypes ctypes
# passes C ints and reads a 4-byte result, truncating them on Win64.
_MESSAGE_ARGTYPES = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
LRESULT = ctypes.c_ssize_t

# Win32 API 函式指標 Win32 API function pointers
PostMessageW = _user32.PostMessageW
PostMessageW.argtypes = _MESSAGE_ARGTYPES
PostMessageW.restype = wintypes.BOOL
SendMessageW = _user32.SendMessageW
SendMessageW.argtypes = _MESSAGE_ARGTYPES
SendMessageW.restype = LRESULT

# 常見的 Windows 訊息對照表 Common Windows messages
messages = {
    "WM_ACTIVATEAPP": 0x001C,
    "WM_CANCELMODE": 0x001F,
    "WM_CHILDACTIVATE": 0x0022,
    "WM_CLOSE": 0x0010,
    "WM_COMPACTING": 0x0041,
    "WM_CREATE": 0x0001,
    "WM_DESTROY": 0x0002,
    "WM_ENABLE": 0x000A,
    "WM_ENTERSIZEMOVE": 0x0231,
    "WM_EXITSIZEMOVE": 0x0232,
    "WM_GETICON": 0x007F,
    "WM_GETMINMAXINFO": 0x0024,
    "WM_INPUTLANGCHANGE": 0x0051,
    "WM_INPUTLANGCHANGEREQUEST": 0x0050,
    "WM_MOVE": 0x0003,
    "WM_MOVING": 0x0216,
    "WM_NCACTIVATE": 0x0086,
    "WM_NCCALCSIZE": 0x0083,
    "WM_NCCREATE": 0x0081,
    "WM_NCDESTROY": 0x0082,
    "WM_NULL": 0x0000,
    "WM_QUERYDRAGICON": 0x0037,
    "WM_QUERYOPEN": 0x0013,
    "WM_QUIT": 0x0012,
    "WM_SHOWWINDOW": 0x0018,
    "WM_SIZE": 0x0005,
    "WM_SIZING": 0x0214,
    "WM_STYLECHANGED": 0x007D,
    "WM_STYLECHANGING": 0x007C,
    "WM_THEMECHANGED": 0x031A,
    "WM_USERCHANGED": 0x0054,
    "WM_WINDOWPOSCHANGED": 0x0047,
    "WM_WINDOWPOSCHANGING": 0x0046,
}


def send_message_to_window(window_name: str, action_message: int,
                           key_code_1: int, key_code_2: int) -> tuple[int, int]:
    """
    使用 SendMessageW 對指定視窗名稱傳送訊息
    Send message to a window by name using SendMessageW

    :param window_name: 視窗標題 Window title
    :param action_message: Windows 訊息代碼 Windows message code
    :param key_code_1: wParam
    :param key_code_2: lParam
    :return: (HWND, 傳送狀態)
    """
    hwnd = get_one_window_hwnd(None, window_name)
    if not hwnd:
        raise AutoControlException(f"Window '{window_name}' not found")
    post_status = SendMessageW(hwnd, action_message, key_code_1, key_code_2)
    return hwnd, post_status


def send_message_to_window_hwnd(hwnd: int, action_message: int,
                                key_code_1: int, key_code_2: int) -> tuple[int, int]:
    """
    使用 SendMessageW 對指定 HWND 傳送訊息
    Send message to a window by HWND using SendMessageW
    """
    post_status = SendMessageW(hwnd, action_message, key_code_1, key_code_2)
    return hwnd, post_status


def post_message_to_window(window_name: str, action_message: int,
                           key_code_1: int, key_code_2: int) -> tuple[int, int]:
    """
    使用 PostMessageW 對指定視窗名稱投遞訊息
    Post message to a window by name using PostMessageW
    """
    hwnd = get_one_window_hwnd(None, window_name)
    if not hwnd:
        raise AutoControlException(f"Window '{window_name}' not found")
    post_status = PostMessageW(hwnd, action_message, key_code_1, key_code_2)
    return hwnd, post_status


def post_message_to_window_hwnd(hwnd: int, action_message: int,
                                key_code_1: int, key_code_2: int) -> tuple[int, int]:
    """
    使用 PostMessageW 對指定 HWND 投遞訊息
    Post message to a window by HWND using PostMessageW
    """
    post_status = PostMessageW(hwnd, action_message, key_code_1, key_code_2)
    return hwnd, post_status
