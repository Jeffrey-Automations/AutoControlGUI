"""Width classes for the adaptive window, with hysteresis so a resize near a boundary does not flicker.

Qt-free: the window asks :func:`classify` on every resize and rearranges its
panes only when the answer changes.
"""
from enum import Enum
from typing import Optional


class WidthClass(str, Enum):
    """How much horizontal room the window has."""

    COMPACT = "compact"      # one pane: navigation and details become overlays
    MEDIUM = "medium"        # navigation docked, details slide over the workspace
    EXPANDED = "expanded"    # navigation, workspace and details side by side


#: Window widths (logical pixels) at which the next class begins.
MEDIUM_FROM = 800
EXPANDED_FROM = 1200
#: How far past a boundary the width must move before the class changes back.
HYSTERESIS = 24

_ORDER = (WidthClass.COMPACT, WidthClass.MEDIUM, WidthClass.EXPANDED)


def _plain(width: int) -> WidthClass:
    if width >= EXPANDED_FROM:
        return WidthClass.EXPANDED
    if width >= MEDIUM_FROM:
        return WidthClass.MEDIUM
    return WidthClass.COMPACT


def classify(width: int, previous: Optional[WidthClass] = None, hysteresis: int = HYSTERESIS) -> WidthClass:
    """Width class for ``width``, sticking with ``previous`` until the width is ``hysteresis`` past a boundary."""
    if width < 0 or hysteresis < 0:
        raise ValueError("width and hysteresis must not be negative")
    plain = _plain(width)
    if previous is None or plain is previous:
        return plain
    # Shrinking leaves a class only once the width is that far below its start;
    # growing enters the next only once the width is that far above it.
    sticky = _plain(width + hysteresis) if _ORDER.index(plain) < _ORDER.index(previous) \
        else _plain(max(0, width - hysteresis))
    return previous if sticky is previous else plain
