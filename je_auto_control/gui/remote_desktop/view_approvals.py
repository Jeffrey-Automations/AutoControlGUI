"""Terminal default-deny approval ownership independent of a Qt page."""
import threading
from typing import Callable

from je_auto_control.utils.remote_desktop.host_access import PendingViewer


class ApprovalRequest:
    """One decision; timeout or retirement cannot be reversed by a late dialog."""

    def __init__(self, pending: PendingViewer) -> None:
        self.pending = pending
        self.event = threading.Event()
        self._lock = threading.Lock()
        self._decision = "denied"

    @property
    def decision(self) -> str:
        with self._lock:
            return self._decision

    @decision.setter
    def decision(self, value: str) -> None:
        self.resolve(value)

    def resolve(self, value: str) -> None:
        with self._lock:
            if not self.event.is_set():
                self._decision = value
                self.event.set()


class ViewApprovals:
    """Wake all waiters and deny new requests when their approving view retires."""

    def __init__(self, notify: Callable[[ApprovalRequest], None], timeout: float) -> None:
        self._notify, self._timeout = notify, timeout
        self._lock = threading.Lock()
        self._pending: set[ApprovalRequest] = set()
        self._retired = False

    def request(self, pending: PendingViewer) -> str | bool:
        request = ApprovalRequest(pending)
        with self._lock:
            if self._retired:
                return False
            self._pending.add(request)
        try:
            self._notify(request)
            completed = request.event.wait(self._timeout)
            request.resolve("denied")
            with self._lock:
                return request.decision if completed and not self._retired else False
        finally:
            with self._lock:
                self._pending.discard(request)

    def retire(self) -> None:
        with self._lock:
            self._retired = True
            pending = tuple(self._pending)
            self._pending.clear()
        for request in pending:
            request.resolve("denied")
