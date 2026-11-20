"""Name the missing image-stack wheel instead of raising ``ModuleNotFoundError``.

``opencv-python`` and ``je_open_cv`` are required dependencies on every
platform (Windows arm64 too, since opencv-python 5.1.0.95 ships a
``win_arm64`` wheel), but an environment can still lack them, for example an
install made with ``--no-deps`` or a source build that failed.

These two accessors sit on the doors every image path goes through, so the
failure names the wheel to install instead of reading like a broken package.
The deeper modules keep their plain lazy ``import cv2`` — wrapping all
seventy-six of them would buy nothing the caller can act on.
"""
from typing import Any

_CV2_HINT = "Image matching requires opencv-python, which is not installed: pip install opencv-python"


def require_cv2() -> Any:
    """Return the ``cv2`` module, or explain why the image stack is absent."""
    try:
        import cv2
    except ImportError as error:
        raise RuntimeError(_CV2_HINT) from error
    return cv2


def require_je_open_cv() -> Any:
    """Return ``je_open_cv.template_detection``, or explain why it is absent."""
    try:
        from je_open_cv import template_detection
    except ImportError as error:
        raise RuntimeError(
            "Template detection requires je_open_cv and opencv-python, which "
            "are not installed: pip install je_open_cv"
        ) from error
    return template_detection
