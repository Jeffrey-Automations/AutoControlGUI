"""Ask RBAC before a tab's privileged call, so a refusal is shown in the tab rather than raised out of a slot.

A tab that calls a headless function directly bypasses the executor, which is
where ``AC_*`` commands are checked against the caller's role. Each such call
first asks :meth:`RefusalLabel.allows` with the command it stands for -- the
same capability table (:data:`~je_auto_control.utils.rbac.policy.COMMAND_CAPABILITIES`)
the executor and the servers use. A refusal is written on the tab's
:class:`RefusalLabel` and, when the tab sits on a workspace page, on that
page's banner. Outside an RBAC scope (the default) nothing is refused, the
label stays hidden and the tab behaves exactly as before.

Work a tab hands to a worker checks again there with :func:`authorized`:
the task runs as whoever started it, so a role that changed in between is
still held to its command.
"""
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from je_auto_control.gui.adaptive.page_banner import page_banner
from je_auto_control.gui.adaptive.surfaces import set_role
from je_auto_control.utils.rbac.authorization import AuthorizationError
from je_auto_control.utils.rbac.policy import authorize_command


def refusal(*commands: str) -> Optional[str]:
    """Why the current caller may not run the first refused of ``commands``; ``None`` when all are allowed."""
    for command in commands:
        try:
            authorize_command(command)
        except AuthorizationError as error:
            return str(error)
    return None


def authorized(command: str, work: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Worker thread: refuse ``command`` as the executor would, then return ``work(*args, **kwargs)``."""
    authorize_command(command)
    return work(*args, **kwargs)


def refused_on(label: QLabel, *commands: str) -> bool:
    """Whether one of ``commands`` is refused; if so the reason goes on ``label`` and on the page's banner."""
    reason = refusal(*commands)
    if reason is None:
        return False
    label.setText(reason)
    banner = page_banner(label)
    if banner is not None:
        banner.show_refusal(reason)
    return True


class RefusalLabel(QLabel):
    """A line in a tab that says why its last privileged command was refused; hidden while none was."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        set_role(self, "warning")
        self.hide()

    def allows(self, *commands: str) -> bool:
        """Whether the current caller may run every one of ``commands``; a refusal is shown, never raised."""
        refused = refused_on(self, *commands)
        if not refused:
            self.setText("")
        self.setHidden(not refused)
        return not refused


__all__ = ["RefusalLabel", "authorized", "refusal", "refused_on"]
