"""Flow Editor tab: visual node-based view of a script.

Round-trips to the same JSON action format the list-based Script
Builder uses, so the two views stay compatible. The list editor is
still the place to edit complex nested branches; this tab is a clear
visual map of what the script will do. Open reads, and Save writes, the
file as a tab task, one at a time; closing the tab drops one still out.
"""
import copy
import functools
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QGraphicsView, QLabel, QMessageBox,
    QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from je_auto_control.gui._dispose import release_resources
from je_auto_control.gui._i18n_helpers import TranslatableMixin
from je_auto_control.gui._tab_task import TabTask
from je_auto_control.gui.adaptive.surfaces import Card, set_role
from je_auto_control.gui.flow_editor.scene import FlowGraphScene
from je_auto_control.gui.language_wrapper.multi_language_wrapper import (
    language_wrapper,
)
from je_auto_control.gui.script_builder.step_model import (
    Step, load_action_file, save_action_file,
)


def _t(key: str) -> str:
    return language_wrapper.translate(key, key)


def _save(path: str, steps: List[Step], extras: Optional[Dict[str, Any]]) -> str:
    """Worker thread: write the action file; return the path written."""
    save_action_file(path, steps, extras)
    return path


class FlowEditorTab(TranslatableMixin, QWidget):
    """Visual node view of the current script (read + export)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tr_init()
        self._scene = FlowGraphScene(self)
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHints(self._view.renderHints())
        self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self._steps: List[Step] = []
        # The other keys of a wrapped file, written back by Save.
        self._file_extras: Optional[Dict[str, Any]] = None
        self._inspector = QTextEdit()
        self._inspector.setReadOnly(True)
        self._status = QLabel()
        self._status_text = self._keyed(self._status)
        self._scene.node_selected.connect(self._on_node_selected)
        self._files = TabTask(self)         # reading or writing the action file
        self._files.result.connect(self._on_file_done)
        self._files.error.connect(self._on_file_failed)
        self._build_layout()

    def dispose(self) -> None:
        """Drop an open or save still out (the write itself runs to its end). Safe to call twice."""
        release_resources(self)

    def retranslate(self) -> None:
        TranslatableMixin.retranslate(self)
        self._apply_translations()

    def _build_layout(self) -> None:
        # Open/save/zoom/fit commands run from the Actions menu; the tab
        # keeps only the graph view, the inspector, and the status line.
        root = QVBoxLayout(self)
        root.setSpacing(12)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._view)
        splitter.addWidget(self._inspector)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        # Start at the same 3:1 split; from the size hints the empty graph got a sliver.
        splitter.setSizes([600, 200])
        root.addWidget(Card().add(splitter, stretch=1), stretch=1)
        self._status.setWordWrap(True)
        set_role(self._status, "hint")
        root.addWidget(self._status)
        self._apply_translations()

    def menu_actions(self) -> List[Tuple[str, Callable[[], None]]]:
        """Expose tab commands to the window-level Actions menu."""
        return [
            ("flow_open_btn", self._on_open),
            ("flow_save_btn", self._on_save),
            ("flow_zoom_in_btn", self._on_zoom_in),
            ("flow_zoom_out_btn", self._on_zoom_out),
            ("flow_fit_btn", self._on_fit),
        ]

    def _apply_translations(self) -> None:
        self._inspector.setPlaceholderText(_t("flow_inspector_placeholder"))

    # --- public ----------------------------------------------------

    def load_steps(self, steps: List[Step]) -> None:
        """Replace the visible graph from a pre-parsed step list."""
        self._steps = list(steps)
        self._file_extras = None
        layout = self._scene.load(self._steps)
        self._status_text.show("flow_loaded", count=len(layout.nodes))

    def steps(self) -> List[Step]:
        return list(self._steps)

    # --- toolbar actions -------------------------------------------

    def _on_open(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, _t("flow_open_btn"), "", "JSON (*.json);;All (*)",
        )
        if path:
            # Through the Script Builder's reader: a file saved with a BOM (Notepad)
            # did not open here, and Save dropped a wrapped file's other keys.
            self._start_file(functools.partial(load_action_file, path), "open")

    def _on_save(self) -> None:
        if not self._steps:
            self._status_text.show("flow_empty")
            return
        path, _selected = QFileDialog.getSaveFileName(
            self, _t("flow_save_btn"), "", "JSON (*.json)",
        )
        if path:
            # A copy: the worker must not see steps the GUI changes meanwhile.
            work = functools.partial(_save, path, copy.deepcopy(self._steps), copy.deepcopy(self._file_extras))
            self._start_file(work, "save")

    def _start_file(self, work: Callable[[], Any], tag: str) -> None:
        if not self._files.start(work, tag=tag):
            self._status_text.show("task_busy")
            return
        self._status_text.show("task_running")

    def _on_file_done(self, result: Any) -> None:
        if self._files.tag == "open":
            steps, extras = result
            self.load_steps(steps)
            self._file_extras = extras
        else:
            self._status_text.show("flow_saved", path=result)

    def _on_file_failed(self, error: object) -> None:
        self._status_text.clear()
        key = "flow_open_btn" if self._files.tag == "open" else "flow_save_btn"
        QMessageBox.warning(self, _t(key), str(error))

    def _on_zoom_in(self) -> None:
        self._view.scale(1.2, 1.2)

    def _on_zoom_out(self) -> None:
        self._view.scale(1 / 1.2, 1 / 1.2)

    def _on_fit(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if rect.isEmpty():
            return
        self._view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _on_node_selected(self, path: Tuple[object, ...]) -> None:
        step = _resolve_step(self._steps, path)
        if step is None:
            return
        body_keys = list(step.bodies.keys())
        arguments = step.params if step.args is None else step.args
        self._inspector.setPlainText(
            f"command: {step.command}\n"
            f"params: {json.dumps(arguments, indent=2, ensure_ascii=False)}\n"
            f"bodies: {body_keys}",
        )


def _resolve_step(roots: List[Step], path: Tuple[object, ...]) -> Optional[Step]:
    if not path:
        return None
    head, *tail = path
    if not isinstance(head, int) or head >= len(roots):
        return None
    step = roots[head]
    for segment in tail:
        if not (isinstance(segment, tuple) and len(segment) == 2):
            return None
        body_key, child_index = segment
        children = step.bodies.get(body_key, [])
        if not isinstance(child_index, int) or child_index >= len(children):
            return None
        step = children[child_index]
    return step


__all__ = ["FlowEditorTab"]
