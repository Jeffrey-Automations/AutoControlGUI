"""Chevrons for drop-down lists and spin boxes, drawn in code and handed to the style sheet.

Once a style sheet places ``QComboBox::drop-down`` or a spin box's buttons, Qt
stops drawing the style's arrow in them, and a style sheet can show an arrow
only from an image file. Fusion's own drop-down box, left unstyled, sat flush
against the rounded right border. So the chevrons are painted with the
navigation rail's glyphs in the theme's colours and cached as files beside the
tab close cross (:mod:`je_auto_control.gui._tab_close_icon`).
"""
from pathlib import Path
from typing import Any, Dict, Optional

from je_auto_control.gui._tab_close_icon import cache_directory
from je_auto_control.utils.logging.logging_instance import autocontrol_logger

_SIDE = 12
_SCALES = (1, 2, 3)


def arrow_file(name: str, colour: str, directory: Optional[Path] = None) -> Optional[Path]:
    """Path of glyph ``name`` (``chevron_down`` / ``chevron_up``) in ``colour``, drawn if not cached yet.

    Written at 1x, 2x and 3x (``name@2x.png``), which Qt picks by screen
    scale. ``None`` when the cache cannot be written.
    """
    from je_auto_control.gui.adaptive.glyphs import glyph_pixmap
    folder = directory if directory is not None else cache_directory()
    base = folder / f"{name}_{colour.lstrip('#').lower()}_{_SIDE}.png"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for scale in _SCALES:
            target = base if scale == 1 else base.with_name(f"{base.stem}@{scale}x.png")
            if not target.is_file() and not glyph_pixmap(name, colour, _SIDE, scale).save(str(target), "PNG"):
                raise OSError(f"could not write {target}")
    except OSError as error:
        autocontrol_logger.warning("arrow icon not cached: %r", error)
        return None
    return base


def _files(tokens: Any, directory: Optional[Path]) -> Optional[Dict[str, str]]:
    wanted = {
        "down": ("chevron_down", tokens.text_muted), "up": ("chevron_up", tokens.text_muted),
        "down_off": ("chevron_down", tokens.border), "up_off": ("chevron_up", tokens.border),
    }
    files = {key: arrow_file(name, colour, directory) for key, (name, colour) in wanted.items()}
    if any(path is None for path in files.values()):
        return None
    return {key: path.as_posix() for key, path in files.items() if path is not None}


def arrow_rules(tokens: Any, directory: Optional[Path] = None) -> str:
    """Style sheet rules that place the drop-down and spin buttons and draw their chevrons.

    An empty string when the cache cannot be written: the controls then keep
    the style's own arrows rather than losing them.
    """
    files = _files(tokens, directory)
    if files is None:
        return ""
    button = 2 * tokens.spacing
    small = max(tokens.radius - 2, 2)
    return f"""QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: {button}px;
    margin-right: {tokens.spacing // 2}px;
    border: none; }}
QComboBox::down-arrow {{ image: url("{files['down']}"); width: {_SIDE}px; height: {_SIDE}px; }}
QComboBox::down-arrow:disabled {{ image: url("{files['down_off']}"); }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: {button}px;
    border: none; border-radius: {small}px; margin-right: {tokens.spacing // 2}px; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; margin-top: 2px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 2px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background-color: {tokens.hover}; }}
QAbstractSpinBox::up-arrow {{ image: url("{files['up']}"); width: {_SIDE - 2}px; height: {_SIDE - 2}px; }}
QAbstractSpinBox::down-arrow {{ image: url("{files['down']}"); width: {_SIDE - 2}px; height: {_SIDE - 2}px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{ image: url("{files['up_off']}"); }}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{ image: url("{files['down_off']}"); }}"""
