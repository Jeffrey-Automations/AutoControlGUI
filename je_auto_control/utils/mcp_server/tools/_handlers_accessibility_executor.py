"""MCP accessibility adapters delegating lazily to executor commands.

Annotations mirror the executor JSON boundary, including heterogeneous payloads.
"""

from typing import Any, Dict, List, Optional


def expand_control(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> bool:
    from je_auto_control.utils.executor.action_executor import _expand_control

    return _expand_control(name, role, app_name, automation_id)


def collapse_control(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> bool:
    from je_auto_control.utils.executor.action_executor import _collapse_control

    return _collapse_control(name, role, app_name, automation_id)


def control_expand_state(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _control_expand_state

    return _control_expand_state(name, role, app_name, automation_id)


def select_control_item(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> bool:
    from je_auto_control.utils.executor.action_executor import _select_control_item

    return _select_control_item(name, role, app_name, automation_id)


def control_range(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _control_range

    return _control_range(name, role, app_name, automation_id)


def set_control_range(
    value: Any,
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> bool:
    from je_auto_control.utils.executor.action_executor import _set_control_range

    return _set_control_range(value, name, role, app_name, automation_id)


def scroll_control_into_view(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> bool:
    from je_auto_control.utils.executor.action_executor import _scroll_control_into_view

    return _scroll_control_into_view(name, role, app_name, automation_id)


def get_control_text(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _get_control_text

    return _get_control_text(name, role, app_name, automation_id)


def find_control_text(
    text: str,
    ignore_case: Any = True,
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> bool:
    from je_auto_control.utils.executor.action_executor import _find_control_text

    return _find_control_text(text, ignore_case, name, role, app_name, automation_id)


def select_control_text(
    text: str,
    ignore_case: Any = True,
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> bool:
    from je_auto_control.utils.executor.action_executor import _select_control_text

    return _select_control_text(text, ignore_case, name, role, app_name, automation_id)


def control_text_attributes(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _control_text_attributes

    return _control_text_attributes(name, role, app_name, automation_id)


def realize_item(
    item_name: str,
    by: str = "name",
    container_name: Optional[str] = None,
    container_role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _realize_item

    return _realize_item(item_name, by, container_name, container_role, app_name, automation_id)


def get_element_properties(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _get_element_properties

    return _get_element_properties(name, role, app_name, automation_id)


def table_headers(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _table_headers

    return _table_headers(name, role, app_name, automation_id)


def table_cell(
    row: Any,
    column: Any,
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _table_cell

    return _table_cell(row, column, name, role, app_name, automation_id)


def cell_by_header(
    row: Any,
    column_header: str,
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _cell_by_header

    return _cell_by_header(row, column_header, name, role, app_name, automation_id)


def move_element(
    x: Any,
    y: Any,
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> bool:
    from je_auto_control.utils.executor.action_executor import _move_element

    return _move_element(x, y, name, role, app_name, automation_id)


def resize_element(
    width: Any,
    height: Any,
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> bool:
    from je_auto_control.utils.executor.action_executor import _resize_element

    return _resize_element(width, height, name, role, app_name, automation_id)


def set_window_state(
    state: str,
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> bool:
    from je_auto_control.utils.executor.action_executor import _set_window_state

    return _set_window_state(state, name, role, app_name, automation_id)


def window_interaction_state(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _window_interaction_state

    return _window_interaction_state(name, role, app_name, automation_id)


def legacy_info(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _legacy_info

    return _legacy_info(name, role, app_name, automation_id)


def legacy_default_action(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> bool:
    from je_auto_control.utils.executor.action_executor import _legacy_default_action

    return _legacy_default_action(name, role, app_name, automation_id)


def get_selection(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _get_selection

    return _get_selection(name, role, app_name, automation_id)


def list_views(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _list_views

    return _list_views(name, role, app_name, automation_id)


def set_view(
    view: str,
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> bool:
    from je_auto_control.utils.executor.action_executor import _set_view

    return _set_view(view, name, role, app_name, automation_id)


def wait_for_focus_change(timeout: Any = 5.0) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _wait_for_focus_change

    return _wait_for_focus_change(timeout)


def get_selected_text(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _get_selected_text

    return _get_selected_text(name, role, app_name, automation_id)


def get_visible_text(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _get_visible_text

    return _get_visible_text(name, role, app_name, automation_id)


def walk_tree(app_name: Optional[str] = None, max_results: int = 500) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _walk_tree

    return _walk_tree(app_name, max_results)


def humanize_role(role: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _humanize_role

    return _humanize_role(role)


def tab_order(app_name: Optional[str] = None, max_results: int = 500) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _tab_order

    return _tab_order(app_name, max_results)


def audit_focus_order(app_name: Optional[str] = None, max_results: int = 500) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _audit_focus_order

    return _audit_focus_order(app_name, max_results)


def focus_control(
    name: Optional[str] = None,
    role: Optional[str] = None,
    app_name: Optional[str] = None,
    automation_id: Optional[str] = None,
) -> bool:
    from je_auto_control.utils.executor.action_executor import _focus_control

    return _focus_control(name, role, app_name, automation_id)


def a11y_record_start(
    app_name: Optional[str] = None, poll_interval_s: float = 0.25, min_movement_px: int = 8
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import (
        _a11y_record_start,
    )

    return _a11y_record_start(
        app_name=app_name,
        poll_interval_s=float(poll_interval_s),
        min_movement_px=int(min_movement_px),
    )


def a11y_record_stop() -> List[Dict[str, Any]]:
    from je_auto_control.utils.executor.action_executor import (
        _a11y_record_stop,
    )

    return _a11y_record_stop()
