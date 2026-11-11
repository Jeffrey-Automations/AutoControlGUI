"""Value-only legacy viewer uploads owned by the shared GUI task controller."""
import functools
from typing import TypeVar

from PySide6.QtCore import QObject

from je_auto_control.gui.remote_desktop.view_lifetime import ViewLifetime
from je_auto_control.gui.tab_task_controller import CancellationToken, TaskHandle, task_controller
from je_auto_control.utils.remote_desktop.viewer import RemoteDesktopViewer


_Owner = TypeVar("_Owner", bound=QObject)

def _send(viewer: RemoteDesktopViewer, source: str, dest: str,
          view: ViewLifetime[_Owner], token: CancellationToken) -> None:
    token.raise_if_cancelled()
    try:
        result = viewer.send_file(source, dest, on_progress=view.callback("_on_file_progress_main"))
    except (OSError, RuntimeError) as error:
        token.raise_if_cancelled()
        view.post("_on_file_complete_main", "", False, str(error), dest)
        return
    token.raise_if_cancelled()
    view.post("_on_file_complete_main", result.transfer_id, bool(result.success), result.error or "", dest)


def start_upload(owner: _Owner, viewer: RemoteDesktopViewer, source: str, dest: str,
                 view: ViewLifetime[_Owner]) -> TaskHandle:
    """Snapshot upload arguments; retiring the view does not disconnect its shared viewer."""
    return task_controller().submit(functools.partial(_send, viewer, source, dest, view), owner=owner)
