"""MCP mobile adapters delegating lazily to executor commands.

Annotations mirror the executor JSON boundary, including heterogeneous payloads.
"""

from typing import Any, Dict, Optional


def android_find_element(
    text: Optional[str] = None,
    resource_id: Optional[str] = None,
    description: Optional[str] = None,
    class_name: Optional[str] = None,
    timeout_s: float = 5.0,
    serial: Optional[str] = None,
) -> Dict[str, int]:
    """Find an Android widget via uiautomator2; return its bounding rect."""
    from je_auto_control.utils.executor.action_executor import (
        _ac_android_find_element,
    )

    return _ac_android_find_element(
        text=text,
        resource_id=resource_id,
        description=description,
        class_name=class_name,
        timeout_s=timeout_s,
        serial=serial,
    )


def android_click_element(
    text: Optional[str] = None,
    resource_id: Optional[str] = None,
    description: Optional[str] = None,
    class_name: Optional[str] = None,
    timeout_s: float = 5.0,
    serial: Optional[str] = None,
) -> Dict[str, int]:
    """Tap the first widget matching the selectors; return click centre."""
    from je_auto_control.utils.executor.action_executor import (
        _ac_android_click_element,
    )

    return _ac_android_click_element(
        text=text,
        resource_id=resource_id,
        description=description,
        class_name=class_name,
        timeout_s=timeout_s,
        serial=serial,
    )


def android_dump_hierarchy(serial: Optional[str] = None) -> str:
    """Return the device's widget tree as an XML string."""
    from je_auto_control.utils.executor.action_executor import (
        _ac_android_dump_hierarchy,
    )

    return _ac_android_dump_hierarchy(serial=serial)


def ios_tap(x: int, y: int, url: Optional[str] = None) -> Dict[str, int]:
    from je_auto_control.utils.executor.action_executor import _ac_ios_tap

    return _ac_ios_tap(x=int(x), y=int(y), url=url)


def ios_swipe(x1: int, y1: int, x2: int, y2: int, duration_s: float = 0.5, url: Optional[str] = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _ac_ios_swipe

    return _ac_ios_swipe(x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2), duration_s=float(duration_s), url=url)


def ios_type(text: str, url: Optional[str] = None) -> str:
    from je_auto_control.utils.executor.action_executor import _ac_ios_type

    return _ac_ios_type(text=text, url=url)


def ios_screenshot(file_path: str, url: Optional[str] = None) -> str:
    from je_auto_control.utils.executor.action_executor import (
        _ac_ios_screenshot,
    )

    return _ac_ios_screenshot(file_path=file_path, url=url)


def ios_find_element(
    name: Optional[str] = None,
    class_name: Optional[str] = None,
    predicate: Optional[str] = None,
    timeout_s: float = 5.0,
    url: Optional[str] = None,
) -> Dict[str, int]:
    from je_auto_control.utils.executor.action_executor import (
        _ac_ios_find_element,
    )

    return _ac_ios_find_element(
        name=name,
        class_name=class_name,
        predicate=predicate,
        timeout_s=float(timeout_s),
        url=url,
    )


def ios_click_element(
    name: Optional[str] = None,
    class_name: Optional[str] = None,
    predicate: Optional[str] = None,
    timeout_s: float = 5.0,
    url: Optional[str] = None,
) -> Dict[str, int]:
    from je_auto_control.utils.executor.action_executor import (
        _ac_ios_click_element,
    )

    return _ac_ios_click_element(
        name=name,
        class_name=class_name,
        predicate=predicate,
        timeout_s=float(timeout_s),
        url=url,
    )


def ios_dump_source(url: Optional[str] = None) -> str:
    from je_auto_control.utils.executor.action_executor import (
        _ac_ios_dump_source,
    )

    return _ac_ios_dump_source(url=url)
