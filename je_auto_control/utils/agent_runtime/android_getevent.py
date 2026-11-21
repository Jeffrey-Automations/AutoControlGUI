"""Report physical Android input from the kernel's evdev stream; injected input never reaches it.

``getevent`` reads ``/dev/input`` devices. Input injected through ``UiAutomation`` (the device
helper) or the ``input`` command is dispatched by the input manager without touching evdev, so
every event line here came from a physical (or, on an emulator, host-forwarded) device. Any such
event marks the device active and calls the takeover handler; a stream that ends or fails makes
the source unhealthy, and an unhealthy source never reports the device idle.
"""
from __future__ import annotations

import re
import socket
import struct
import threading
import time
from typing import Any, Callable

from je_auto_control.utils.agent_runtime.errors import AgentTaskError

GETEVENT_COMMAND = "/system/bin/getevent -l"
# "/dev/input/event3: EV_ABS       ABS_MT_POSITION_X    000001f4"
_EVENT = re.compile(rb"^/dev/input/event\d+: +EV_[A-Z]+ ")
_PACKET = struct.Struct("<BI")
_READ_LIMIT = 1 << 20


class GeteventSource:
    """One owned ``getevent`` stream on one selected transport; ``close`` ends it."""

    def __init__(self, open_stream: Callable[[], socket.socket], *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._open_stream, self._clock = open_stream, clock
        self._lock = threading.Lock()
        self._handler: Callable[[], None] | None = None
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started: float | None = None
        self._last_activity: float | None = None
        self._failed = False
        self._pending = b""

    def set_handler(self, handler: Callable[[], None]) -> None:
        """Call ``handler`` on the reader thread for every physical event batch."""
        with self._lock:
            self._handler = handler

    def start(self) -> None:
        """Open the stream once; a second start is refused."""
        with self._lock:
            if self._thread is not None:
                raise AgentTaskError("Android physical input source was already started")
            self._socket = self._open_stream()
            self._socket.settimeout(0.2)
            self._started = self._clock()
            self._thread = threading.Thread(target=self._run, name="AndroidGetevent", daemon=True)
            self._thread.start()

    @property
    def healthy(self) -> bool:
        """Whether the stream is running and has not failed."""
        with self._lock:
            return self._thread is not None and not self._failed and not self._stop.is_set()

    def idle_for(self) -> float:
        """Seconds since the later of stream start and the last physical event; 0 when unhealthy."""
        with self._lock:
            if self._thread is None or self._failed or self._stop.is_set() or self._started is None:
                return 0.0
            since = self._started if self._last_activity is None else max(self._started, self._last_activity)
            return max(0.0, self._clock() - since)

    def _run(self) -> None:
        try:
            self._read_packets()
        except (OSError, AgentTaskError, struct.error):
            pass  # recorded below: any end of the stream makes the source unhealthy
        finally:
            with self._lock:
                if not self._stop.is_set():
                    self._failed = True
            self._notify()

    def _receive(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            if self._stop.is_set() or self._socket is None:
                raise AgentTaskError("Android physical input stream was closed")
            try:
                part = self._socket.recv(size - len(data))
            except socket.timeout:
                continue
            if not part:
                raise AgentTaskError("Android physical input stream ended")
            data.extend(part)
        return bytes(data)

    def _read_packets(self) -> None:
        while not self._stop.is_set():
            kind, size = _PACKET.unpack(self._receive(_PACKET.size))
            if size > _READ_LIMIT or kind not in (1, 2):
                raise AgentTaskError("Android physical input stream ended or is malformed")
            body = self._receive(size)
            if kind == 1 and self._lines(body):
                with self._lock:
                    self._last_activity = self._clock()
                self._notify()

    def _lines(self, body: bytes) -> bool:
        """Whether a stdout chunk completes at least one physical event line."""
        data = self._pending + body
        *complete, self._pending = data.split(b"\n")
        if len(self._pending) > 4096:
            raise AgentTaskError("Android physical input stream line exceeds its bound")
        return any(_EVENT.match(line) for line in complete)

    def _notify(self) -> None:
        with self._lock:
            handler = self._handler
        if handler is not None:
            handler()

    def close(self) -> None:
        """Stop reading and close the stream, which ends the remote ``getevent``."""
        with self._lock:
            self._stop.set()
            connection, self._socket = self._socket, None
            thread = self._thread
        if connection is not None:
            connection.close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(1)


def getevent_source(server: Any, transport_id: int, *, timeout: float = 5,
                    clock: Callable[[], float] = time.monotonic) -> GeteventSource:
    """A source over one managed ADB server and selected transport; nothing opens until ``start``."""
    return GeteventSource(lambda: server.open_shell_stream(transport_id, GETEVENT_COMMAND, timeout=timeout),
                          clock=clock)
