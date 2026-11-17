"""The image argument the matching and analysis modules accept, as one shared alias.

A source is a path (``str``, ``bytes`` or ``os.PathLike``), a PIL image, a
numpy array, or anything else ``numpy.asarray`` turns into one; ``None`` where a
parameter allows it means the live screen. numpy is read as ``Any`` by the
typing contract (``follow_imports = "skip"`` in ``pyproject.toml``), so the
array half of that union could not be spelt precisely anyway. This module is
the one place the alias is bound, as ``SDK_ANY_ADAPTERS`` in
``test_typing_modernization_contract.py`` records; the modules around it import
it instead of each writing ``ImageSource = Any``. Imports nothing at run time.
"""
from typing import Any

ImageSource = Any

__all__ = ["ImageSource"]
