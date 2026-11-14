"""Adaptive layout building blocks shared by the window and every page.

``breakpoints`` is Qt-free; the rest needs PySide6 and is imported from the
submodules directly (``from je_auto_control.gui.adaptive.surfaces import Card``),
so importing this package loads no Qt.
"""
from je_auto_control.gui.adaptive.breakpoints import WidthClass, classify

__all__ = ["WidthClass", "classify"]
