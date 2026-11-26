"""Wire-format helpers for :mod:`session`: transfer dispatchers and reply frames.

Pure functions with no session state: they pull a transfer's arguments out
of its JSON payload and call the backend, and they build and stamp the
OPENED / ERROR / transfer reply frames the session sends back. The names
are private to the passthrough package; ``session`` re-exports the wire
bounds where callers have always read them.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Callable, Dict, List, Optional

from je_auto_control.utils.usb.passthrough.backend import UsbHandle
from je_auto_control.utils.usb.passthrough.protocol import (
    MAX_PAYLOAD_BYTES, REQUEST_ID_KEY, Frame, Opcode,
)


# ---------------------------------------------------------------------------
# Transfer dispatchers — pure functions that pull args out of the JSON
# payload and call the right backend method.
# ---------------------------------------------------------------------------


#: Bounds on numbers taken from the wire. A control transfer's wLength is a
#: 16-bit field; bulk and interrupt reads are capped so one request cannot
#: make the host allocate (and base64, and fragment) gigabytes.
MAX_CONTROL_LENGTH = 0xFFFF
MAX_ENDPOINT_LENGTH = 1024 * 1024
MAX_TIMEOUT_MS = 60_000


def _run_transfer(dispatcher: Callable[[UsbHandle, Dict[str, Any]], bytes],
                  handle: UsbHandle, request: Dict[str, Any]) -> Dict[str, Any]:
    """The transfer reply body: the data, or the backend's error."""
    try:
        result = dispatcher(handle, request)
    except Exception as error:  # noqa: BLE001  # pylint: disable=broad-except  # reason: backends raise their own error types; reported to the viewer
        return {"ok": False, "error": str(error)}
    return {"ok": True, "data": base64.b64encode(result).decode("ascii")}


def _bounded(request: Dict[str, Any], key: str, default: int, upper: int) -> int:
    value = int(request.get(key, default))
    if not 0 <= value <= upper:
        raise ValueError(f"{key} must be within 0..{upper}, got {value}")
    return value


def _control_handler(handle: UsbHandle, request: Dict[str, Any]) -> bytes:
    payload = _decode_b64(request.get("data"))
    return handle.control_transfer(
        bm_request_type=int(request["bm_request_type"]),
        b_request=int(request["b_request"]),
        w_value=int(request.get("w_value", 0)),
        w_index=int(request.get("w_index", 0)),
        data=payload,
        length=_bounded(request, "length", 0, MAX_CONTROL_LENGTH),
        timeout_ms=_bounded(request, "timeout_ms", 1000, MAX_TIMEOUT_MS),
    )


def _bulk_handler(handle: UsbHandle, request: Dict[str, Any]) -> bytes:
    return _endpoint_call(handle.bulk_transfer, request)


def _interrupt_handler(handle: UsbHandle, request: Dict[str, Any]) -> bytes:
    return _endpoint_call(handle.interrupt_transfer, request)


def _endpoint_call(method: Callable[..., bytes],
                   request: Dict[str, Any]) -> bytes:
    direction = str(request.get("direction", ""))
    if direction not in ("in", "out"):
        raise RuntimeError(f"direction must be 'in' or 'out', got {direction!r}")
    return method(
        endpoint=int(request["endpoint"]),
        direction=direction,
        data=_decode_b64(request.get("data")),
        length=_bounded(request, "length", 0, MAX_ENDPOINT_LENGTH),
        timeout_ms=_bounded(request, "timeout_ms", 1000, MAX_TIMEOUT_MS),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_REPLY_OPCODES: Dict[Opcode, Opcode] = {
    Opcode.CTRL: Opcode.CTRL,
    Opcode.BULK: Opcode.BULK,
    Opcode.INT: Opcode.INT,
}


def _reply_opcode(request_op: Opcode) -> Opcode:
    return _REPLY_OPCODES.get(request_op, Opcode.ERROR)


def _is_misbehaviour(replies: List[Frame]) -> bool:
    """True if the replies indicate a viewer-caused protocol failure.

    Counts ERROR frames and failed OPENED replies as strikes; a device
    transfer that fails at the backend (CTRL/BULK/INT with ok=false) is
    the device's fault, not the viewer's, so it is not counted.
    """
    for reply in replies:
        if reply.op == Opcode.ERROR:
            return True
        if reply.op == Opcode.OPENED:
            try:
                body = json.loads(reply.payload.decode("utf-8"))
            except ValueError:
                return True
            if not body.get("ok"):
                return True
    return False


def _decode_b64(value: Any) -> bytes:
    if value is None or value == "":
        return b""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return base64.b64decode(str(value))


def _opened_failure(claim_id: int, message: str) -> Frame:
    return Frame(
        op=Opcode.OPENED, claim_id=claim_id,
        payload=_encode_json_payload({"ok": False, "error": message}),
    )


def _error_frame(claim_id: int, message: str) -> Frame:
    return Frame(
        op=Opcode.ERROR, claim_id=claim_id,
        payload=_encode_json_payload({"error": message}),
    )


#: Replies that are always one frame, so the id can be added after the fact.
_SINGLE_FRAME_REPLIES = (Opcode.OPENED, Opcode.CLOSED, Opcode.ERROR)


def _identified(body: Dict[str, Any], request_id: Optional[str]) -> Dict[str, Any]:
    """``body`` with the request's id added, if the request had one."""
    if request_id is not None:
        body[REQUEST_ID_KEY] = request_id
    return body


def _with_request_id(frame: Frame, request_id: Optional[str]) -> Frame:
    """Echo ``request_id`` in a single-frame reply; other frames pass through.

    CREDIT is a grant rather than a reply and never carries an id; LIST and
    transfer replies got theirs before they were fragmented.
    """
    if request_id is None or frame.op not in _SINGLE_FRAME_REPLIES:
        return frame
    try:
        body = _decode_json_payload(frame.payload)
    except ValueError:
        return frame
    payload = _encode_json_payload(_identified(body, request_id))
    if len(payload) > MAX_PAYLOAD_BYTES:
        return frame    # an unidentified reply still beats none at all
    return Frame(op=frame.op, flags=frame.flags, claim_id=frame.claim_id,
                 payload=payload)


def _encode_json_payload(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _decode_json_payload(payload: bytes) -> Dict[str, Any]:
    if not payload:
        raise ValueError("empty payload")
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("payload must be a JSON object")
    return decoded
