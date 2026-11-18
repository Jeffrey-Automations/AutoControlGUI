"""Refuse a pinned image another local account could redirect or plant code beside.

The image lease keeps the file's bytes fixed, but ``CreateProcess`` resolves the
path again by name and the loader searches the image's own directory for DLLs.
So a lease is only enough when the path itself cannot change underneath it:

* every directory from the drive root down to the image is a real directory,
  not a junction or symbolic link, and grants no account outside SYSTEM,
  Administrators, TrustedInstaller and the running user the right to rename,
  delete, re-link, rewrite the ACL of, or add files to it;
* the leased handle's final path is the requested path, so no reparse point,
  short name, ``subst`` drive or network redirection sits anywhere in it.

The directories are checked from the root down: once a parent is protected, the
name of its child can no longer change, so the chain stays as measured.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import ntpath
import re
import sys
from typing import Any, Callable, NoReturn, Protocol

from .models import FailureReason, MemoryObservationError

_DIRECTORY = 0x10
_REPARSE_POINT = 0x400
_INHERIT_ONLY = 0x08
# Rights that let a holder add a file (a planted DLL), rename, delete or re-link an entry,
# turn the directory into a junction, or take over its ACL or owner.
_UNSAFE_RIGHTS = (0x2 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | 0x10000000 | 0x40000000)
_ALLOW_TYPES = frozenset({0x0, 0x9})
# Deny, audit, alarm, mandatory-label and attribute ACEs grant nothing.
_NON_GRANTING_TYPES = frozenset({0x1, 0x2, 0x3, 0x6, 0x7, 0x8, 0xA, 0xC, 0xD, 0xE, 0xF,
                                 0x10, 0x11, 0x12, 0x13, 0x14})
_WELL_KNOWN_TRUSTED = frozenset({
    "S-1-5-18",  # LocalSystem
    "S-1-5-32-544",  # BUILTIN\Administrators
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",  # TrustedInstaller
})
_DRIVE = re.compile(r"[A-Za-z]:")
_PATH_CHARACTERS = 32768


@dataclass(frozen=True)
class AccessEntry:
    """One ACE as the check needs it; ``sid`` is ``None`` for a layout that is not parsed."""

    kind: int
    flags: int
    mask: int
    sid: str | None


@dataclass(frozen=True)
class DirectorySecurity:
    """Owner, DACL (``None`` for a NULL DACL, which grants everyone everything) and attributes."""

    owner: str
    entries: tuple[AccessEntry, ...] | None
    attributes: int


class SecuritySource(Protocol):
    """Where the check reads the running user, a handle's final path and a directory's ACL."""

    def user_sid(self) -> str: ...

    def final_path(self, handle: int) -> str: ...

    def directory(self, path: str) -> DirectorySecurity: ...


def _fail(reason: FailureReason) -> NoReturn:
    raise MemoryObservationError(reason)


def local_drive_path(path: str) -> str:
    """Return ``path`` normalized as ``X:\\...``, or refuse a UNC, device, relative or bare-drive path."""
    if not isinstance(path, str) or not path or "\0" in path or path.startswith(("\\\\", "//")):
        _fail(FailureReason.UNSUPPORTED)
    normal = ntpath.normpath(path)
    drive, rest = ntpath.splitdrive(normal)
    if _DRIVE.fullmatch(drive) is None or not rest.startswith("\\") or rest == "\\":
        _fail(FailureReason.UNSUPPORTED)
    return normal


def _directories(path: str) -> list[str]:
    """Every directory above ``path``, drive root first."""
    drive, rest = ntpath.splitdrive(path)
    chain = [drive + "\\"]
    for part in [part for part in rest.split("\\") if part][:-1]:
        chain.append(ntpath.join(chain[-1], part))
    return chain


def _unsafe(entry: AccessEntry, trusted: frozenset[str]) -> bool:
    if entry.flags & _INHERIT_ONLY or entry.kind in _NON_GRANTING_TYPES:
        return False
    if entry.kind not in _ALLOW_TYPES or entry.sid is None:
        return True  # an allow ACE this check cannot read is not assumed harmless
    return bool(entry.mask & _UNSAFE_RIGHTS) and entry.sid not in trusted


def _protected(security: DirectorySecurity, trusted: frozenset[str]) -> bool:
    if not security.attributes & _DIRECTORY or security.attributes & _REPARSE_POINT:
        return False
    if security.owner not in trusted or security.entries is None:
        return False
    return not any(_unsafe(entry, trusted) for entry in security.entries)


def _dos_path(final: str) -> str:
    if final.startswith("\\\\?\\") and not final[4:].upper().startswith("UNC\\"):
        return final[4:]
    _fail(FailureReason.UNSUPPORTED)


def require_trusted_image(path: str, handle: int, source: SecuritySource) -> None:
    """Refuse unless ``path`` cannot be redirected and the leased ``handle`` is the file it names."""
    local = local_drive_path(path)
    trusted = _WELL_KNOWN_TRUSTED | {source.user_sid()}
    for directory in _directories(local):
        if not _protected(source.directory(directory), trusted):
            _fail(FailureReason.UNSUPPORTED)
    if ntpath.normcase(_dos_path(source.final_path(handle))) != ntpath.normcase(local):
        _fail(FailureReason.TARGET_CHANGED)


class _Acl(ctypes.Structure):
    _fields_ = [("revision", ctypes.c_ubyte), ("sbz1", ctypes.c_ubyte), ("size", ctypes.c_ushort),
                ("count", ctypes.c_ushort), ("sbz2", ctypes.c_ushort)]


class _AceHeader(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("size", ctypes.c_ushort)]


_PVOID = ctypes.c_void_p
_DWORD = ctypes.c_uint32
_BOOL = ctypes.c_int


class NativeSecuritySource:
    """Read ACLs, attributes and final paths through advapi32 and kernel32."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            _fail(FailureReason.UNSUPPORTED)
        try:
            self._advapi: Any = ctypes.WinDLL("advapi32", use_last_error=True)
            self._kernel: Any = ctypes.WinDLL("kernel32", use_last_error=True)
            self._bind()
        except (OSError, AttributeError):
            _fail(FailureReason.UNSUPPORTED)

    def _bind(self) -> None:
        advapi, kernel = self._advapi, self._kernel
        signatures: tuple[tuple[Any, list[Any], Any], ...] = (
            (advapi.GetNamedSecurityInfoW, [ctypes.c_wchar_p, ctypes.c_int, _DWORD, ctypes.POINTER(_PVOID),
                                            ctypes.POINTER(_PVOID), ctypes.POINTER(_PVOID),
                                            ctypes.POINTER(_PVOID), ctypes.POINTER(_PVOID)], _DWORD),
            (advapi.ConvertSidToStringSidW, [_PVOID, ctypes.POINTER(_PVOID)], _BOOL),
            (advapi.IsValidSid, [_PVOID], _BOOL),
            (advapi.GetAce, [_PVOID, _DWORD, ctypes.POINTER(_PVOID)], _BOOL),
            (advapi.OpenProcessToken, [_PVOID, _DWORD, ctypes.POINTER(_PVOID)], _BOOL),
            (advapi.GetTokenInformation, [_PVOID, ctypes.c_int, _PVOID, _DWORD, ctypes.POINTER(_DWORD)], _BOOL),
            (kernel.GetCurrentProcess, [], _PVOID),
            (kernel.CloseHandle, [_PVOID], _BOOL),
            (kernel.LocalFree, [_PVOID], _PVOID),
            (kernel.GetFileAttributesW, [ctypes.c_wchar_p], _DWORD),
            (kernel.GetFinalPathNameByHandleW, [_PVOID, ctypes.c_wchar_p, _DWORD, _DWORD], _DWORD),
        )
        for function, arguments, result in signatures:
            function.argtypes, function.restype = arguments, result

    def _sid_text(self, sid: int) -> str:
        if not sid or not self._advapi.IsValidSid(sid):
            _fail(FailureReason.UNSUPPORTED)
        text = _PVOID()
        if not self._advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)) or not text.value:
            _fail(FailureReason.UNSUPPORTED)
        try:
            return ctypes.wstring_at(text.value)
        finally:
            self._kernel.LocalFree(text)

    def user_sid(self) -> str:
        """The SID of the account this process runs as."""
        token, size = _PVOID(), _DWORD()
        if not self._advapi.OpenProcessToken(self._kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            _fail(FailureReason.UNSUPPORTED)
        try:
            self._advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            if not 0 < size.value <= 4096:
                _fail(FailureReason.UNSUPPORTED)
            buffer = ctypes.create_string_buffer(size.value)
            if not self._advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
                _fail(FailureReason.UNSUPPORTED)
            # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first member is the SID pointer.
            return self._sid_text(_PVOID.from_buffer(buffer).value or 0)
        finally:
            self._kernel.CloseHandle(token)

    def final_path(self, handle: int) -> str:
        """The normalized ``\\\\?\\X:\\...`` path of the file ``handle`` refers to."""
        buffer = ctypes.create_unicode_buffer(_PATH_CHARACTERS)
        length = self._kernel.GetFinalPathNameByHandleW(handle, buffer, _PATH_CHARACTERS, 0)
        if not 0 < length < _PATH_CHARACTERS:
            _fail(FailureReason.UNSUPPORTED)
        return buffer.value

    def directory(self, path: str) -> DirectorySecurity:
        """Owner, DACL entries and attributes of ``path`` itself (a reparse point is not followed)."""
        attributes = self._kernel.GetFileAttributesW(path)
        if attributes == 0xFFFFFFFF:
            _fail(FailureReason.UNSUPPORTED)
        owner, dacl, descriptor = _PVOID(), _PVOID(), _PVOID()
        # SE_FILE_OBJECT; OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
        if self._advapi.GetNamedSecurityInfoW(path, 1, 0x1 | 0x4, ctypes.byref(owner), None,
                                              ctypes.byref(dacl), None, ctypes.byref(descriptor)):
            _fail(FailureReason.UNSUPPORTED)
        try:
            entries = None if not dacl.value else self._entries(dacl.value)
            return DirectorySecurity(self._sid_text(owner.value or 0), entries, attributes)
        finally:
            self._kernel.LocalFree(descriptor)

    def _entries(self, dacl: int) -> tuple[AccessEntry, ...]:
        entries = []
        for index in range(_Acl.from_address(dacl).count):
            ace = _PVOID()
            if not self._advapi.GetAce(dacl, index, ctypes.byref(ace)) or not ace.value:
                _fail(FailureReason.UNSUPPORTED)
            entries.append(self._entry(ace.value))
        return tuple(entries)

    def _entry(self, address: int) -> AccessEntry:
        header = _AceHeader.from_address(address)
        mask = _DWORD.from_address(address + 4).value
        # ACCESS_ALLOWED_ACE and its callback form keep the SID right after the mask.
        sid = self._sid_text(address + 8) if header.kind in _ALLOW_TYPES and header.size >= 16 else None
        return AccessEntry(header.kind, header.flags, mask, sid)


def native_image_trust() -> Callable[[str, int], None]:
    """Bind the check to the native source; constructed on first lease, never at import."""
    source = NativeSecuritySource()
    return lambda path, handle: require_trusted_image(path, handle, source)


__all__ = ["AccessEntry", "DirectorySecurity", "NativeSecuritySource", "SecuritySource",
           "local_drive_path", "native_image_trust", "require_trusted_image"]
