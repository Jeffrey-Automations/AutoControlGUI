"""The typed accessors the tabs use in place of a cast at every call site (offscreen Qt)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLabel, QPushButton, QTableWidget, QTableWidgetItem  # noqa: E402

from je_auto_control.gui._i18n_helpers import TranslatableMixin  # noqa: E402
from je_auto_control.gui._qt_typed import as_widget, decoded_image, filled_item  # noqa: E402
from je_auto_control.utils.exception.exceptions import AutoControlException  # noqa: E402


@pytest.fixture(autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def test_as_widget_is_the_object_itself():
    label = QLabel("x")
    assert as_widget(label) is label
    label.deleteLater()


def test_a_filled_cell_is_returned_and_a_missing_one_is_a_typed_error():
    table = QTableWidget(1, 2)
    item = QTableWidgetItem("job-1")
    table.setItem(0, 0, item)
    assert filled_item(table, 0, 0) is item
    assert filled_item(table, 0, 0).text() == "job-1"
    with pytest.raises(AutoControlException, match="row 0, column 1"):
        filled_item(table, 0, 1)
    table.deleteLater()


def test_tr_hands_back_the_widget_it_was_given():
    """``_tr`` is generic over the widget class; at run time it has always returned its argument."""

    class _Tab(TranslatableMixin):
        """A translatable holder."""

    tab = _Tab()
    button = QPushButton()
    assert tab._tr(button, "audit_run") is button
    assert button.text() != ""
    button.deleteLater()


def test_the_scoped_enum_spellings_are_the_members_the_short_ones_named():
    assert QAbstractItemView.EditTrigger.NoEditTriggers is QAbstractItemView.NoEditTriggers
    assert Qt.ItemFlag.ItemIsEditable is Qt.ItemIsEditable
    assert Qt.ItemDataRole.UserRole is Qt.UserRole


def _encoded(image_format: str) -> bytes:
    image = QImage(6, 4, QImage.Format.Format_RGB32)
    image.fill(0xFF2040)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, image_format)
    return bytes(data)


@pytest.mark.parametrize("image_format", ["PNG", "JPEG"])
def test_an_encoded_frame_decodes_to_its_image(image_format):
    image = decoded_image(_encoded(image_format), image_format)
    assert not image.isNull() and (image.width(), image.height()) == (6, 4)


@pytest.mark.parametrize("payload", [b"", b"not an image", bytes([0xFF, 0xD8, 0xFF]) + bytes(16)])
def test_bytes_that_do_not_decode_are_a_null_image(payload):
    assert decoded_image(payload, "JPEG").isNull()


def test_the_binding_still_rejects_the_bytes_format_its_stub_asks_for():
    """When this stops raising, ``QImage.fromData`` can be called directly again."""
    with pytest.raises(ValueError):
        QImage.fromData(_encoded("PNG"), b"PNG")
