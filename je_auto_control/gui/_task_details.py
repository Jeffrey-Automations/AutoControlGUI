"""Execution details a :class:`~je_auto_control.gui._tab_task.TabTask` publishes for the page it runs on.

The workspace's details pane shows what the current page's
:class:`~je_auto_control.gui.workspace_details.ExecutionDetailsSource`
publishes, and the page's :class:`~je_auto_control.gui.adaptive.page_banner.PageBanner`
reports a failed run. A tab task finds its page -- the widget the workspace holds as a
tab, which may be an ancestor of the panel that owns the task -- and creates
that source the first time it runs, so every page that runs background work
reports it: running, stopping, then succeeded, cancelled or error, with the
progress the work reports.
"""
from typing import Optional, Tuple

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QWidget

from je_auto_control.gui.adaptive.page_banner import PageBanner, page_banner, page_of
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper
from je_auto_control.gui.tab_task_controller import TaskTimeout
from je_auto_control.gui.workspace_details import ExecutionDetails, ExecutionDetailsSource, ExecutionPhase
from je_auto_control.utils.executor.run_control import ExecutionStopped
from je_auto_control.utils.logging.secret_scope import scrub_secret_text
from je_auto_control.utils.rbac.authorization import AuthorizationError

#: The longest error text the details pane is given.
SUMMARY_LIMIT = 500


def details_source_for(owner: QWidget) -> ExecutionDetailsSource:
    """The details source of ``owner``'s page, created on first use."""
    page = page_of(owner)
    found = page.findChild(ExecutionDetailsSource, options=Qt.FindChildOption.FindDirectChildrenOnly)
    return found if isinstance(found, ExecutionDetailsSource) else ExecutionDetailsSource(page)


def _counts(value: object) -> Optional[Tuple[int, int]]:
    """``(completed, total)`` from a reported progress value; ``None`` when it carries no count."""
    completed, total = getattr(value, "completed", None), getattr(value, "total", None)
    if isinstance(completed, int):
        return completed, total if isinstance(total, int) else 0
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], int):
        return value[1], 0          # (request_id, count): a count with no known total
    return None


class TaskDetails:
    """Turns one tab task's lifecycle into execution details for its page."""

    def __init__(self, task: QObject) -> None:
        self._task = task
        self._outcome: Optional[Tuple[str, object]] = None
        self._stopped = False
        self._completed = self._total = 0

    def started(self) -> None:
        """A run began; it clears the banner's report of the last one."""
        self._outcome, self._stopped = None, False
        self._completed = self._total = 0
        self._publish("running")
        banner = self._banner()
        if banner is not None:
            banner.clear("error")

    def stopping(self) -> None:
        """Stop was requested for a run that unwinds before it ends."""
        self._stopped = True
        self._publish("stopping")

    def progressed(self, value: object) -> None:
        """The work reported progress."""
        counts = _counts(value)
        if counts is not None:
            self._completed, self._total = counts
            self._publish("stopping" if self._stopped else "running")

    def noted(self, kind: str, value: object = None) -> None:
        """Remember the run's outcome (``"result"`` or ``"error"``) until it finishes."""
        self._outcome = (kind, value)

    def finished(self) -> None:
        """The run ended: publish how."""
        kind, error = self._outcome or ("", None)
        if kind == "error" and not isinstance(error, ExecutionStopped):
            if isinstance(error, TaskTimeout):
                summary = language_wrapper.translate("task_timed_out", "task_timed_out")
            else:
                summary = scrub_secret_text(f"{type(error).__name__}: {error}")[:SUMMARY_LIMIT]
            self._publish("error", summary)
            self._report(error, summary)
        elif kind == "result" and not self._stopped:
            self._publish("succeeded")
        else:   # cancelled, stopped, or the owner went away
            self._publish("cancelled")

    def _banner(self) -> Optional[PageBanner]:
        owner = self._task.parent()
        return page_banner(owner) if isinstance(owner, QWidget) else None

    def _report(self, error: object, summary: str) -> None:
        banner = self._banner()
        if banner is None:
            return
        if isinstance(error, AuthorizationError):
            banner.show_refusal(summary)
        else:
            banner.show_error(summary)

    def _publish(self, phase: ExecutionPhase, summary: str = "") -> None:
        owner = self._task.parent()
        if not isinstance(owner, QWidget):
            return
        total = self._total if phase in ("running", "stopping") else 0
        details_source_for(owner).publish(ExecutionDetails(phase, summary, self._completed, total))


__all__ = ["SUMMARY_LIMIT", "TaskDetails", "details_source_for", "page_of"]
