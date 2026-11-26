"""Read-only scoped controls and a one-to-one pixel preview for managed task requests.

The preview image is checked and decoded on a thread of the view's own
(:class:`~je_auto_control.gui._latest_decoder.LatestDecoder`); the newest
observation wins, and one cleared or replaced meanwhile is not painted.
"""
from __future__ import annotations

from typing import Any
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QLabel, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from je_auto_control.gui._i18n_helpers import KeyedText
from je_auto_control.gui._latest_decoder import LatestDecoder
from je_auto_control.gui.adaptive.surfaces import set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.images import observation_image_bytes


def _decode_observation_image(image: dict[str, Any]) -> QImage:
    """Decoder thread: the strict-masked JPEG checked, then decoded; :class:`AgentTaskError` when it is not."""
    pixels = observation_image_bytes(image)
    decoded = QImage()
    # No format argument: the header says JPEG, and that argument's type
    # differs between the PySide6 releases the contract is checked against.
    if not decoded.loadFromData(pixels):
        raise AgentTaskError("observation preview image could not be decoded")
    return decoded


class _Image(QLabel):
    picked = Signal(object)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Offer rendered image pixels without dispatching input or scaling coordinates."""
        x, y = math.floor(event.position().x()), math.floor(event.position().y())
        pixmap = self.pixmap()
        if event.button() == Qt.MouseButton.LeftButton and not pixmap.isNull():
            if 0 <= x < pixmap.width() and 0 <= y < pixmap.height():
                self.picked.emit({"image_point": [x, y]})
                event.accept()
                return
        super().mousePressEvent(event)


class AgentObservationView(QWidget):
    """Present one observation; selections only propose a reference to its immutable identifier."""

    picked = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.observation_id = ""
        self._indices: list[int] = []
        self._shown = 0                     # bumped by clear(): an image decoded for an older frame is dropped
        self._decoder = LatestDecoder(self, _decode_observation_image, self._image_decoded, self._image_failed)
        self._elements = QTableWidget(0, 4)
        self._elements.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._elements.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._elements.cellClicked.connect(self._pick_element)
        self._image = _Image()
        self._image.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._image.picked.connect(self.picked.emit)
        self._loading = KeyedText(self._image)     # "Loading" until the picture replaces it
        self.setProperty("role", "bare")
        self._notice = QLabel()
        self._notice.setWordWrap(True)
        set_role(self._notice, "danger")
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setWidget(self._image)
        layout = QVBoxLayout(self)
        layout.addWidget(self._elements)
        layout.addWidget(self._notice)
        layout.addWidget(scroll)
        self.clear()
        self.retranslate()

    def retranslate(self) -> None:
        """Translate columns without obtaining a new observation."""
        self._loading.retranslate()
        self._elements.setHorizontalHeaderLabels([language_wrapper.translate("agent_element_" + name, name)
                                                   for name in ("index", "name", "role", "bounds")])

    def clear(self) -> None:
        """Discard all frame-local selections and pixels on task changes or action dispatch."""
        self.observation_id = ""
        self._shown += 1
        self._indices.clear()
        self._elements.setRowCount(0)
        self._loading.forget()
        self._image.setPixmap(QPixmap())
        self._image.setFixedSize(1, 1)
        self._notice.clear()

    def present(self, observation: dict[str, Any]) -> None:
        """Display bounded elements and validate the strict-masked JPEG before Qt decodes it."""
        self.clear()
        identifier, data = observation.get("observation_id"), observation.get("data")
        if not isinstance(identifier, str) or not identifier or not isinstance(data, dict):
            raise AgentTaskError("observation preview requires an identifier and data")
        self.observation_id = identifier
        elements = data.get("elements", [])
        if not isinstance(elements, list) or len(elements) > 10000:
            raise AgentTaskError("observation preview elements exceed their bound")
        self._present_elements(elements)
        image = data.get("image")
        if isinstance(image, dict):
            self._present_image(image)

    def _present_elements(self, elements: list[Any]) -> None:
        for index, element in enumerate(elements):
            if not isinstance(element, dict) or element.get("index", index) != index:
                raise AgentTaskError("observation preview element index is ambiguous")
            self._indices.append(index)
            self._elements.insertRow(index)
            for column, name in enumerate(("index", "name", "role", "bounds")):
                value = index if name == "index" else element.get(name, "")
                if name == "bounds" and "selector" in element:
                    value = {"selector": element["selector"], "frame": element.get("frame", "")}
                self._elements.setItem(index, column, QTableWidgetItem(str(value)))

    def dispose(self) -> None:
        """Drop an image still being decoded and end the decoder's thread; safe to call twice."""
        self._shown += 1
        self._decoder.stop()

    def _present_image(self, image: dict[str, Any]) -> None:
        self._loading.show("gui_op_loading")
        self._image.setFixedSize(self._image.sizeHint())
        self._decoder.submit(image, self._shown)

    def _image_decoded(self, shown: int, image: QImage) -> None:
        if shown != self._shown:
            return
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(1.0)
        self._loading.forget()
        self._image.setPixmap(pixmap)
        self._image.setFixedSize(pixmap.size())

    def _image_failed(self, shown: int, error: object) -> None:
        if shown != self._shown:
            return
        self._loading.clear()
        self._image.setFixedSize(1, 1)
        if isinstance(error, AgentTaskError):
            self._notice.setText(str(error))
        else:
            self._notice.setText(f"observation preview image could not be decoded: {error}")

    def _pick_element(self, row: int, _column: int) -> None:
        if self.observation_id and 0 <= row < len(self._indices):
            self.picked.emit({"element_index": self._indices[row]})
