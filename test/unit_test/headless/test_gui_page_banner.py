"""A page says when its last run failed, and when the active role cannot run its commands.

A failure or an RBAC refusal used to show only in each panel's own status
line, in its own words, or not at all on pages without one. The workspace now
gives every page a banner under its header for both.
"""
import os
import threading

import pytest

from je_auto_control.utils.rbac import AuthorizationContext, Role, authorization_scope
from je_auto_control.utils.rbac.authorization import AuthorizationError
from je_auto_control.utils.rbac.policy import refused_commands


def test_refused_commands_follow_the_role_and_ignore_unscoped_callers():
    assert refused_commands(["AC_journal_read", "AC_diagnose"]) == []            # no RBAC scope
    viewer = AuthorizationContext("viewer", Role.VIEWER)
    refused = refused_commands(["AC_journal_read", "AC_not_a_listed_command"], viewer)
    assert refused == ["AC_journal_read"]                                        # an unlisted one never is
    admin = AuthorizationContext("admin", Role.ADMIN)
    assert refused_commands(["AC_journal_read"], admin) == []
    with authorization_scope(viewer):
        assert refused_commands(["AC_journal_read"]) == ["AC_journal_read"]


pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from je_auto_control.gui._tab_task import TabTask  # noqa: E402
from je_auto_control.gui.adaptive.page_banner import PageBanner, page_banner  # noqa: E402
from je_auto_control.gui.language_wrapper.multi_language_wrapper import language_wrapper  # noqa: E402
from headless._qt_settle import pump_until  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class _Reader(QWidget):
    """A panel that needs journal access, inside a page, running a task."""

    REQUIRED_COMMANDS = ("AC_journal_read",)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.task = TabTask(self)


class _Page(QWidget):
    def __init__(self):
        super().__init__()
        self.reader = _Reader()
        QVBoxLayout(self).addWidget(self.reader)


@pytest.fixture
def shell():
    from je_auto_control.gui.tab_registry import TabEntry, TabRegistry
    from je_auto_control.gui.workspace import WorkspaceShell
    widget = WorkspaceShell(TabRegistry([TabEntry("journal", "tab_run_history", _Page),
                                         TabEntry("other", "other", QWidget)]))
    yield widget
    widget.deleteLater()
    _APP.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _t(key):
    return language_wrapper.translate(key, key)


def _banner(shell):
    banner = page_banner(shell.tabs.currentWidget())
    assert isinstance(banner, PageBanner)
    return banner


def test_the_banner_sits_under_the_header_and_starts_hidden(shell):
    shell.activate_tab("journal")
    page = shell.tabs.currentWidget()
    banner = _banner(shell)
    assert page.layout().indexOf(banner) == 1                 # the header is at 0
    assert banner.isHidden()


def test_a_role_that_cannot_run_the_page_is_told_so_when_it_opens(shell):
    with authorization_scope(AuthorizationContext("viewer", Role.VIEWER)):
        shell.activate_tab("journal")
    banner = _banner(shell)
    assert not banner.isHidden() and banner.kind == "permission"
    assert banner.message.text() == _t("page_banner_permission").format(role="viewer", commands="AC_journal_read")
    shell.activate_tab("other")
    with authorization_scope(AuthorizationContext("admin", Role.ADMIN)):
        shell.activate_tab("journal")                          # shown again: the admin may
    assert banner.isHidden()


def test_a_failed_run_is_reported_and_the_next_run_clears_it(shell):
    shell.activate_tab("journal")
    task = shell.tabs.currentWidget().reader.task
    banner = _banner(shell)

    def fail():
        raise ValueError("journal is corrupt")

    assert task.start(fail)
    assert pump_until(lambda: not banner.isHidden())
    assert banner.kind == "error"
    assert banner.message.text() == _t("page_banner_error").format(detail="ValueError: journal is corrupt")
    release = threading.Event()
    assert task.start(lambda: release.wait(10.0))
    assert banner.isHidden()                                   # a new run clears the old report
    release.set()
    assert pump_until(lambda: not task.running)
    assert banner.isHidden()


def test_a_refused_run_is_a_permission_banner(shell):
    shell.activate_tab("journal")
    task = shell.tabs.currentWidget().reader.task

    def refuse():
        raise AuthorizationError("AC_journal_read needs the 'drive_input' capability", capability="drive_input")

    assert task.start(refuse)
    banner = _banner(shell)
    assert pump_until(lambda: not banner.isHidden())
    assert banner.kind == "permission"
    assert "drive_input" in banner.message.text()


def test_dismiss_hides_the_banner_and_the_text_follows_the_language(shell):
    shell.activate_tab("journal")
    banner = _banner(shell)
    banner.show_error("boom")
    previous = language_wrapper.language
    try:
        language_wrapper.reset_language("Traditional_Chinese")
        from je_auto_control.gui.adaptive.surfaces import retranslate_surfaces
        retranslate_surfaces(shell.tabs.currentWidget())       # what a language switch runs on each page
        assert banner.message.text() == language_wrapper.translate("page_banner_error", "").format(detail="boom")
        assert "關閉" in banner.dismiss.text()
    finally:
        language_wrapper.reset_language(previous)
    banner.dismiss.linkActivated.emit("dismiss")
    assert banner.isHidden()
