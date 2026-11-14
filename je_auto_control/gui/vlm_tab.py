"""VLM tab: describe a UI element in words and have a model find it.

The model round trip runs as a :class:`~je_auto_control.gui._tab_task.TabTask`:
one request at a time, a Stop in the Actions menu, and a deadline. A stopped or
timed-out Click never clicks: :func:`click_by_description` checks the task's
cancellation once the model has answered, before it moves the mouse.
"""
import functools
from typing import Optional

from PySide6.QtWidgets import (
    QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.gui.tab_task_controller import TaskTimeout
from je_auto_control.utils.vision.vlm_api import (
    click_by_description, locate_by_description,
)

#: How long one locate or click may take. Each backend gives a request 30 s and
#: its SDK retries a failed one twice, so this leaves room for all three tries.
REQUEST_DEADLINE_S = 120.0


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


class VLMTab(TranslatableMixin, QWidget):
    """Drive a vision-language model to locate or click described elements."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._description = QLineEdit()
        self._model = QLineEdit()
        self._status = QLabel()
        self._last_result = QLabel()
        self._task = TabTask(self)          # one model request at a time, off the GUI thread
        self._task.result.connect(self._show_outcome)
        self._task.error.connect(self._show_task_error)
        self._apply_placeholders()
        self._build_layout()

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        self._apply_placeholders()

    def _apply_placeholders(self) -> None:
        self._description.setPlaceholderText(_t("vlm_desc_placeholder"))
        self._model.setPlaceholderText(_t("vlm_model_placeholder"))

    def _build_layout(self) -> None:
        # Locate/click commands run from the Actions menu; the tab keeps
        # only the description/model inputs and the result labels.
        root = QVBoxLayout(self)
        root.setSpacing(12)
        form = QFormLayout()
        form.addRow(self._tr(QLabel(), "vlm_desc_label"), self._description)
        form.addRow(self._tr(QLabel(), "vlm_model_label"), self._model)
        root.addWidget(Card().add(form))
        self._last_result.setWordWrap(True)
        self._status.setWordWrap(True)
        set_role(self._status, "hint")
        root.addWidget(self._last_result)
        root.addWidget(self._status)
        root.addStretch()

    def dispose(self) -> None:
        """Release what the tab holds beyond its widgets: the model request still out.

        The request is cancelled: its answer is dropped and a Click does not
        click. The HTTP call itself runs to its end. Called by
        ``close_tab(key, release=True)`` before the widget is deleted; safe to call twice.
        """
        release_resources(self)

    def menu_actions(self) -> list:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("vlm_locate", self._on_locate),
            ("vlm_click", self._on_click),
            ("task_stop", self._on_stop),
        ]

    def _collect_inputs(self):
        description = self._description.text().strip()
        if not description:
            self._status.setText(_t("vlm_desc_required"))
            return None
        model = self._model.text().strip() or None
        return description, model

    def _run_off_gui_thread(self, call, tag: str) -> None:
        """The VLM round trip (network, seconds) froze the window on the GUI thread."""
        if not self._task.start(call, tag=tag, timeout_s=REQUEST_DEADLINE_S):
            self._status.setText(_t("task_busy"))
            return
        self._status.setText(_t("task_running"))

    def _on_stop(self) -> None:
        if self._task.stop():
            self._status.setText(_t("task_stopped"))

    def _show_outcome(self, value: object) -> None:
        if self._task.tag == "click":
            self._show_clicked(value)
        else:
            self._show_located(value)

    def _show_task_error(self, error: object) -> None:
        if isinstance(error, TaskTimeout):
            self._status.setText(_t("task_timed_out"))
            return
        self._status.setText(f"{_t('vlm_error')}: {error}")

    def _on_locate(self) -> None:
        inputs = self._collect_inputs()
        if inputs is None:
            return
        description, model = inputs
        self._run_off_gui_thread(functools.partial(locate_by_description, description, model=model), "locate")

    def _show_located(self, coords) -> None:
        if coords is None:
            self._status.setText(_t("vlm_not_found"))
            self._last_result.setText("")
            return
        self._last_result.setText(
            _t("vlm_result").replace("{x}", str(coords[0]))
                             .replace("{y}", str(coords[1])),
        )
        self._status.setText(_t("vlm_ok"))

    def _on_click(self) -> None:
        inputs = self._collect_inputs()
        if inputs is None:
            return
        description, model = inputs
        self._run_off_gui_thread(functools.partial(click_by_description, description, model=model), "click")

    def _show_clicked(self, ok) -> None:
        self._status.setText(_t("vlm_ok") if ok else _t("vlm_not_found"))
