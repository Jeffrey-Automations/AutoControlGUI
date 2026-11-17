"""MCP desktop adapters delegating lazily to executor commands.

Annotations mirror the executor JSON boundary, including heterogeneous payloads.
"""

from typing import Any, Dict


def move_along_path(waypoints: Any, easing: str = "linear", per_segment_steps: Any = 20) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _move_along_path

    return _move_along_path(waypoints, easing, per_segment_steps)


def drag_path(
    waypoints: Any,
    button: str = "mouse_left",
    easing: str = "linear",
    per_segment_steps: Any = 20,
    step_delay_s: Any = 0.0,
    settle_s: Any = 0.0,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _drag_path

    return _drag_path(waypoints, button, easing, per_segment_steps, step_delay_s, settle_s)


def set_field_text(text: str, clear: str = "select_all", paste: Any = False, modifier: str = "ctrl") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _set_field_text

    return _set_field_text(text, clear, paste, modifier)


def hold_key(key: str, duration_s: Any = 1.0, rate_hz: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _hold_key

    return _hold_key(key, duration_s, rate_hz)


def move_mouse_relative(dx: Any, dy: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _move_mouse_relative

    return _move_mouse_relative(dx, dy)


def input_reachable() -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import (
        _input_reachable,
    )

    return _input_reachable()


def type_unicode(text: str, modifier: str = "ctrl") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _type_unicode

    return _type_unicode(text, modifier)


def type_unicode_keys(text: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _type_unicode_keys

    return _type_unicode_keys(text)


def type_unicode_text(text: str, modifier: str = "ctrl") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _type_unicode_text

    return _type_unicode_text(text, modifier)


def with_modifiers(modifiers: Any, actions: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _with_modifiers

    return _with_modifiers(modifiers, actions)


def tile_rect(slot: str, screen: Any = None, gap: Any = 0) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _tile_rect

    return _tile_rect(slot, screen, gap)


def grid_rects(rows: Any, cols: Any, screen: Any = None, gap: Any = 0) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _grid_rects

    return _grid_rects(rows, cols, screen, gap)


def cascade_rects(count: Any, screen: Any = None, offset: Any = 30, size: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _cascade_rects

    return _cascade_rects(count, screen, offset, size)


def arrange_grid(titles: Any, rows: Any = None, cols: Any = None, gap: Any = 0) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _arrange_grid

    return _arrange_grid(titles, rows, cols, gap)


def arrange_cascade(titles: Any, offset: Any = 30) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _arrange_cascade

    return _arrange_cascade(titles, offset)


def enumerate_monitors() -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _enumerate_monitors

    return _enumerate_monitors()


def monitor_at_point(x: Any, y: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _monitor_at_point

    return _monitor_at_point(x, y)


def set_clipboard_html(html: str, fragment_plaintext: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _set_clipboard_html

    return _set_clipboard_html(html, fragment_plaintext)


def get_clipboard_html() -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _get_clipboard_html

    return _get_clipboard_html()


def set_clipboard_files(paths: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _set_clipboard_files

    return _set_clipboard_files(paths)


def get_clipboard_files() -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _get_clipboard_files

    return _get_clipboard_files()


def set_clipboard_rtf(text: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _set_clipboard_rtf

    return _set_clipboard_rtf(text)


def get_clipboard_rtf() -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _get_clipboard_rtf

    return _get_clipboard_rtf()


def set_clipboard_csv(rows: Any, delimiter: str = ",") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _set_clipboard_csv

    return _set_clipboard_csv(rows, delimiter)


def get_clipboard_csv(delimiter: str = ",") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _get_clipboard_csv

    return _get_clipboard_csv(delimiter)


def clipboard_formats() -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _clipboard_formats

    return _clipboard_formats()


def classify_formats(formats: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _classify_formats

    return _classify_formats(formats)


def diff_formats(before: Any, after: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _diff_formats

    return _diff_formats(before, after)


def plan_file_drop(paths: Any, point: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _plan_file_drop

    return _plan_file_drop(paths, point)


def drop_files(hwnd: Any, paths: Any, point: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _drop_files

    return _drop_files(hwnd, paths, point)


def set_topmost(title: str, on: Any = True) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _set_topmost

    return _set_topmost(title, on)


def bring_to_front(title: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _bring_to_front

    return _bring_to_front(title)


def send_to_back(title: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _send_to_back

    return _send_to_back(title)


def get_client_rect(title: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _get_client_rect

    return _get_client_rect(title)


def client_point(title: str, x: Any, y: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _client_point

    return _client_point(title, x, y)
