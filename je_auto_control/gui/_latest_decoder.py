"""Decode the newest image for one view on its own thread; a newer source replaces one not yet decoded.

A remote screen sends JPEG frames several times a second, and the views decoded
each one in the slot that received it, on the GUI thread. :class:`LatestDecoder`
takes that off the GUI thread for one view:

* **A thread of its own, started on first use.** The decode loop runs as one
  :mod:`~je_auto_control.gui.tab_task_controller` task owned by the decoder; it
  ends once nothing has arrived for ``idle_s`` and starts again with the next
  source, so a view that shows nothing holds no thread.
* **Latest wins.** :meth:`LatestDecoder.submit` replaces a source that has not
  been decoded yet, and the next decode waits until the GUI thread has taken
  the previous image: neither the input nor Qt's event queue grows when the
  GUI thread is slower than the source.
* **Tagged.** Each source carries a tag (a session number, an observation id);
  ``on_decoded(tag, image)`` gets it back, so the view drops an image of a
  session that has since changed. A ``decode`` that raises reaches
  ``on_failed(tag, error)`` instead, and the next source still decodes.
* **Stop.** :meth:`LatestDecoder.stop` -- the view's ``dispose()`` -- closes the
  decoder for good: nothing more is delivered and the thread wakes and ends.
  Destroying the owner does the same.

``decode`` runs on the decoder thread, so it builds a ``QImage`` (which may be
made off the GUI thread), never a ``QPixmap`` or a widget; it must be a
module-level function or a partial of one, holding plain values.
"""
import functools
import threading
from typing import Any, Callable, Optional, Tuple

from PySide6.QtCore import QObject
from PySide6.QtGui import QImage

from je_auto_control.gui._qt_typed import decoded_image
from je_auto_control.gui._weak_call import Callback, WeakCall
from je_auto_control.gui.tab_task_controller import CancellationToken, task_controller
from je_auto_control.utils.logging.logging_instance import autocontrol_logger

#: Seconds the decoder thread waits for a new source before it ends.
IDLE_S = 5.0

_Item = Tuple[object, object]


def decode_jpeg(data: bytes) -> QImage:
    """Decoder thread: ``data`` decoded as JPEG; a null image when it does not decode."""
    return decoded_image(data, "JPEG")


class _Mailbox:
    """The one source waiting to be decoded, shared by the GUI thread and the decoder thread."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._source: Optional[_Item] = None
        self._in_flight = False             # a decoded image is on its way to the GUI thread
        self._serving = False               # a decode loop is running for this mailbox
        self._closed = False

    @property
    def closed(self) -> bool:
        """Whether :meth:`close` was called."""
        with self._cond:
            return self._closed

    @property
    def busy(self) -> bool:
        """Whether a source is waiting or its image has not been taken yet."""
        with self._cond:
            return not self._closed and (self._source is not None or self._in_flight)

    def put(self, tag: object, source: object) -> bool:
        """GUI thread: offer ``source``, replacing one not decoded yet; return whether a loop must start."""
        with self._cond:
            if self._closed:
                return False
            self._source = (tag, source)
            start, self._serving = not self._serving, True
            self._cond.notify_all()
            return start

    def take(self, idle_s: float) -> Optional[_Item]:
        """Decoder thread: the next source to decode, or ``None`` when the loop should end."""
        with self._cond:
            while not self._closed:
                if self._source is not None and not self._in_flight:
                    item, self._source = self._source, None
                    self._in_flight = True
                    return item
                idle = self._source is None and not self._in_flight
                if not self._cond.wait(idle_s) and idle and self._source is None and not self._in_flight:
                    break
            self._serving = False
            return None

    def taken(self) -> None:
        """GUI thread: the image in flight was delivered; the next source may be decoded."""
        with self._cond:
            self._in_flight = False
            self._cond.notify_all()

    def close(self) -> None:
        """Any thread: accept nothing more and wake the loop so it ends."""
        with self._cond:
            self._closed = True
            self._source = None
            self._cond.notify_all()


def _decode_loop(mailbox: _Mailbox, decode: Callable[[Any], Any], idle_s: float,
                 token: CancellationToken) -> None:
    """Decoder thread: decode each source the mailbox hands over and report ``(tag, ok, value)``."""
    token.on_cancel(mailbox.close)
    while True:
        item = mailbox.take(idle_s)
        if item is None:
            return
        tag, source = item
        try:
            outcome = (tag, True, decode(source))
        except Exception as error:  # noqa: BLE001  # reason: delivered to the view's on_failed; the next source still decodes
            outcome = (tag, False, error)
        token.report_progress(outcome)


class LatestDecoder(QObject):
    """Decodes the newest source for its parent view on a thread of its own; see the module docstring."""

    def __init__(self, owner: QObject, decode: Callable[[Any], Any], on_decoded: Callback,
                 on_failed: Callback = None, *, idle_s: float = IDLE_S) -> None:
        super().__init__(owner)
        self._decode = decode
        self._idle_s = idle_s
        self._mailbox = _Mailbox()
        self._on_decoded = WeakCall(on_decoded)
        self._on_failed = WeakCall(on_failed)

    @property
    def busy(self) -> bool:
        """Whether a source handed to :meth:`submit` has not been delivered yet."""
        return self._mailbox.busy

    def submit(self, source: object, tag: object = None) -> None:
        """GUI thread: decode ``source`` off the GUI thread; it replaces a source not decoded yet."""
        if self._mailbox.put(tag, source):
            loop = functools.partial(_decode_loop, self._mailbox, self._decode, self._idle_s)
            handle = task_controller().submit(loop, owner=self)
            handle.progress.connect(self._deliver)

    def stop(self) -> None:
        """Deliver nothing more and end the thread; for good (``dispose()``). Safe to call twice."""
        self._mailbox.close()
        self._on_decoded = self._on_failed = WeakCall(None)
        task_controller().cancel_all(self)

    def _deliver(self, outcome: Tuple[object, bool, object]) -> None:
        """GUI thread: hand one decoded image (or a decode error) to the view."""
        self._mailbox.taken()
        if self._mailbox.closed:
            return
        tag, ok, value = outcome
        if ok:
            self._on_decoded(tag, value)
        elif not self._on_failed(tag, value):
            autocontrol_logger.debug("image decode failed: %r", value)


__all__ = ["IDLE_S", "LatestDecoder", "decode_jpeg"]
