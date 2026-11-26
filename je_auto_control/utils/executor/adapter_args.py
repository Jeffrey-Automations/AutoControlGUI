"""Argument checks the executor adapters share: JSON lists and finite numbers.

An adapter's arguments arrive from JSON action files, the socket server, the
scheduler and the Script Builder, where a list is often a JSON string and a
number can be ``NaN`` (Python's ``json`` reads it). Two shapes went wrong:
a string decoded to a string, which ``list()`` then split into characters
(``AC_arrange_grid`` given ``'"Notepad"'`` moved every window whose title
held an ``N``, an ``o``, ...), and a ``NaN`` threshold, which compares false
both ways and so turned an "absent" check into a pass. Imports no ``PySide6``.
"""
import json
import math
from typing import Any, List

from je_auto_control.utils.exception.exceptions import AutoControlActionException


def json_list(value: Any, name: str = "value") -> List[Any]:
    """``value`` as a list; a string is decoded as JSON and must hold a list."""
    if not isinstance(value, str):
        return list(value)
    decoded = json.loads(value)
    if not isinstance(decoded, list):
        raise AutoControlActionException(
            f"{name} must be a list or a JSON list, got {type(decoded).__name__}: {value!r}")
    return decoded


def finite_float(value: Any, name: str) -> float:
    """``value`` as a float, refusing ``NaN`` and the infinities."""
    number = float(value)
    if not math.isfinite(number):
        raise AutoControlActionException(f"{name} must be a finite number, got {value!r}")
    return number
