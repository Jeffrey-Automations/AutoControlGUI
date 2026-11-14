"""Frame conversion and optional recording without retaining a remote view."""
from typing import Callable, Optional

from PySide6.QtGui import QImage

from je_auto_control.gui.remote_desktop._webrtc_types import AvFrameT, SessionRecorderT
from je_auto_control.gui.remote_desktop.webrtc_panel_common import _av_frame_to_qimage
from je_auto_control.utils.logging.logging_instance import autocontrol_logger


class ViewFrames:
    def __init__(self, deliver: Callable[[QImage], None],
                 recorder: Optional[Callable[[], Optional[SessionRecorderT]]] = None) -> None:
        self._deliver, self._recorder = deliver, recorder

    def __call__(self, frame: AvFrameT) -> None:
        recorder = self._recorder() if self._recorder is not None else None
        if recorder is not None:
            try:
                recorder.write_frame(frame)
            except (RuntimeError, OSError) as error:
                autocontrol_logger.debug("recorder write: %r", error)
        image = _av_frame_to_qimage(frame)
        if image is not None:
            self._deliver(image)
