"""Derive same-user service ownership from reviewed service keys, folding case with the OS table."""
import ctypes
import hashlib
import sys
import unicodedata
from pathlib import Path
from typing import Callable

from .service_status import ServiceFailure, ServiceQueryError

# Characters that could hide or confuse a reviewed name, or whose casing can change
# between Unicode versions: controls, format, surrogates, private use, unassigned,
# and every separator except the plain space SCM names may contain.
_REFUSED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp", "Zs"})

Upcase = Callable[[int], int]


def _printable_ascii(service_key: str) -> bool:
    return all(" " <= char <= "~" for char in service_key)


def _hidden(char: str) -> bool:
    return char != " " and unicodedata.category(char) in _REFUSED_CATEGORIES


def _validate(service_key: str) -> None:
    if type(service_key) is not str or not service_key or "/" in service_key or "\\" in service_key:
        raise ServiceQueryError(ServiceFailure.UNSUPPORTED)
    if _printable_ascii(service_key):
        units = len(service_key)
    elif any(_hidden(char) for char in service_key):
        raise ServiceQueryError(ServiceFailure.UNSUPPORTED)
    else:
        units = len(service_key.encode("utf-16-le")) // 2
    if units > 256:
        raise ServiceQueryError(ServiceFailure.UNSUPPORTED)


def _os_upcase() -> Upcase:
    """The NT casing table that case-insensitive registry service keys are compared with."""
    if sys.platform != "win32":
        raise ServiceQueryError(ServiceFailure.UNSUPPORTED)
    try:
        function = ctypes.WinDLL("ntdll").RtlUpcaseUnicodeChar
    except (OSError, AttributeError):
        raise ServiceQueryError(ServiceFailure.UNAVAILABLE) from None
    function.argtypes = (ctypes.c_uint16,)
    function.restype = ctypes.c_uint16
    return lambda unit: int(function(unit))


def _upcased(service_key: str, upcase: Upcase) -> str:
    encoded = service_key.encode("utf-16-le")
    units = [int.from_bytes(encoded[index:index + 2], "little") for index in range(0, len(encoded), 2)]
    folded = []
    for unit in units:
        mapped = upcase(unit)
        if type(mapped) is not int or not 0 <= mapped <= 0xFFFF:
            raise ServiceQueryError(ServiceFailure.UNAVAILABLE)
        folded.append(mapped.to_bytes(2, "little"))
    try:
        return b"".join(folded).decode("utf-16-le")
    except UnicodeError:  # a table that splits a surrogate pair is not one names can be keyed by
        raise ServiceQueryError(ServiceFailure.UNAVAILABLE) from None


def _ascii_scope(service_key: str) -> str:
    return hashlib.sha256(b"local-scm-ascii-v1\0" + service_key.lower().encode("ascii")).hexdigest()


def service_scope(service_key: str, *, upcase: Upcase | None = None) -> str:
    """Return one ownership scope for every spelling the OS casing table folds together.

    Printable ASCII keys keep their original ASCII-folded scope. Other keys are
    folded per UTF-16 unit with the NT upcase table (``RtlUpcaseUnicodeChar``),
    which is what case-insensitive registry keys, and so service keys, compare
    with; it never folds less than SCM does, so two spellings of one service
    cannot hold separate locks. Python's own case mapping differs from that
    table (``ß``, ``ı``, the Kelvin sign) and is never used. A key that folds to
    printable ASCII shares that ASCII scope. Without the OS table, non-ASCII
    keys are unsupported.
    """
    _validate(service_key)
    if _printable_ascii(service_key):
        return _ascii_scope(service_key)
    folded = _upcased(service_key, upcase if upcase is not None else _os_upcase())
    if _printable_ascii(folded):
        return _ascii_scope(folded)
    return hashlib.sha256(b"local-scm-upcase-v1\0" + folded.encode("utf-16-le")).hexdigest()


def service_resource(service_key: str, lock_root: Path | None = None) -> Path:
    """Share a lock across profiles/databases of this OS user, not external SCM clients."""
    root = lock_root if lock_root is not None else Path.home() / ".je_auto_control" / "service_ownership"
    return root / (service_scope(service_key) + ".lock")
