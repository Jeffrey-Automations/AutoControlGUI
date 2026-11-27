"""Who may talk to the TCP socket server: its token, its file and the RBAC users.

The server used to run any command for any local process, including the
admin-only ones and ``quit_server``. Now the first line a client sends on a
connection must be ``AUTH <token>``; the server answers ``AUTH_OK`` and then
reads one command exactly as before.

Which token is accepted:

* RBAC off (``JE_AUTOCONTROL_RBAC_USERS`` unset): the server token -- the
  ``token`` argument, else ``$JE_AUTOCONTROL_SOCKET_TOKEN``, else a fresh
  ``secrets.token_urlsafe(32)``. It is written to an owner-only file,
  ``~/.je_auto_control/socket_server_<port>.token`` by default, for local
  clients to read, and it grants the trusted behaviour the server always had.
* RBAC on: a user's token from the store, and nothing else -- as on REST and
  MCP, an identity-less token would switch RBAC off for whoever holds it.
  Each command then runs under that user's role.

Failed attempts are counted per client address by the REST gate
(:class:`~je_auto_control.utils.rest_api.rest_auth.RestAuthGate`), so the
lockout and its rule -- a valid token is never locked out -- are shared.
Standard library only; imports no ``PySide6``.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from je_auto_control.utils.action_signing._private_file import write_private_text
from je_auto_control.utils.exception.exceptions import AutoControlException
from je_auto_control.utils.logging.logging_instance import autocontrol_logger
from je_auto_control.utils.rbac.authorization import AuthorizationContext, user_store_from_env
from je_auto_control.utils.rbac.users import UserStore
from je_auto_control.utils.rest_api.rest_auth import AuthResult, RestAuthGate

#: Names a token the server accepts, and the one a client sends, when no
#: explicit token is given.
TOKEN_ENV = "JE_AUTOCONTROL_SOCKET_TOKEN"  # nosec B105  # reason: an environment variable name, not a credential
#: The first line of an authenticated connection: ``AUTH <token>``.
AUTH_PREFIX = "AUTH "
#: The server's answer to a valid ``AUTH`` line.
AUTH_OK = "AUTH_OK"
_TOKEN_BYTES = 32
_MAX_TOKEN_CHARS = 1024
# The per-connection rate is not what is limited here -- every command is a
# new connection -- only the failed attempts (eight a minute per address).
_ATTEMPTS_PER_MINUTE = 6000.0
_ATTEMPT_BURST = 600.0


class SocketAuthError(AutoControlException, ValueError):
    """A socket token is malformed, missing, or was refused by the server."""


def default_token_path(port: int) -> Path:
    """``~/.je_auto_control/socket_server_<port>.token``, resolved when called."""
    return Path.home() / ".je_auto_control" / f"socket_server_{int(port)}.token"


def validate_token(token: str) -> str:
    """``token`` when it can travel on one ``AUTH`` line; raise otherwise."""
    if not isinstance(token, str) or not token:
        raise SocketAuthError("the socket token must be a non-empty string")
    if len(token) > _MAX_TOKEN_CHARS or any(char.isspace() for char in token):
        raise SocketAuthError(
            f"the socket token must be at most {_MAX_TOKEN_CHARS} characters, without whitespace")
    return token


def resolve_server_token(token: Optional[str]) -> str:
    """The explicit token, else ``$JE_AUTOCONTROL_SOCKET_TOKEN``, else a new one."""
    if token is not None:
        return validate_token(token)
    from_env = os.environ.get(TOKEN_ENV, "").strip()
    if from_env:
        return validate_token(from_env)
    return secrets.token_urlsafe(_TOKEN_BYTES)


def write_token_file(path: Path, token: str) -> Path:
    """Write ``token`` to ``path`` atomically, readable by the current user only."""
    target = Path(os.path.realpath(os.path.expanduser(str(path))))
    target.parent.mkdir(parents=True, exist_ok=True)
    write_private_text(target, token + "\n")
    return target


def read_token_file(path: Path) -> str:
    """The token stored at ``path``; :class:`SocketAuthError` when there is none."""
    target = Path(os.path.realpath(os.path.expanduser(str(path))))
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as error:
        raise SocketAuthError(f"no socket server token at {target}: {error}") from error
    return validate_token(text.strip())


def remove_token_file(path: Path, token: str) -> None:
    """Delete ``path`` if it still holds ``token``: a newer server's file is kept."""
    try:
        if path.read_text(encoding="utf-8").strip() == token:
            path.unlink()
    except OSError as error:
        autocontrol_logger.debug("socket token file %s not removed: %r", path, error)


@dataclass(frozen=True)
class SocketAuthResult:
    """What :meth:`SocketAuth.check` decided, and the caller under RBAC."""

    verdict: str
    context: Optional[AuthorizationContext] = None

    @property
    def ok(self) -> bool:
        """``True`` when the token was accepted."""
        return self.verdict == "ok"


class SocketAuth:
    """The socket server's authentication policy.

    ``require_auth=False`` is the legacy opt-out: every connection is served
    as trusted without an ``AUTH`` line. Otherwise the server token (RBAC
    off) or a user's token (RBAC on) is required.
    """

    def __init__(self, token: Optional[str] = None, *, require_auth: bool = True,
                 user_store: Optional[UserStore] = None) -> None:
        self.require_auth = bool(require_auth)
        self.token: Optional[str] = token
        self.user_store = user_store
        self._gate: Optional[RestAuthGate] = None
        if self.require_auth:
            self.token = validate_token(token) if token is not None else None
            self._gate = RestAuthGate(
                self.token or secrets.token_urlsafe(_TOKEN_BYTES),
                requests_per_minute=_ATTEMPTS_PER_MINUTE, burst=_ATTEMPT_BURST,
                user_store=user_store)

    @classmethod
    def from_environment(cls, token: Optional[str] = None, *,
                         require_auth: bool = True) -> "SocketAuth":
        """The policy for a server started now: its token and the RBAC store, if any."""
        if not require_auth:
            return cls(require_auth=False)
        store = user_store_from_env()
        if store is not None:
            return cls(None, user_store=store)  # no server token: it would pass without a role
        return cls(resolve_server_token(token))

    @property
    def rbac_enabled(self) -> bool:
        """``True`` when only RBAC user tokens are accepted."""
        return self.require_auth and self.user_store is not None

    def check(self, client: str, token: str) -> SocketAuthResult:
        """Rate-limit, then authenticate ``token`` sent from ``client``."""
        if self._gate is None:
            return SocketAuthResult("ok")
        result: AuthResult = self._gate.authenticate(
            client_ip=client, header_value=f"Bearer {token}")
        if result.verdict == "ok" and self.rbac_enabled and result.context is None:
            return SocketAuthResult("unauthorized")  # never an identity-less pass under RBAC
        return SocketAuthResult(result.verdict, result.context)


__all__ = [
    "AUTH_OK", "AUTH_PREFIX", "SocketAuth", "SocketAuthError", "SocketAuthResult", "TOKEN_ENV",
    "default_token_path", "read_token_file", "remove_token_file", "resolve_server_token",
    "validate_token", "write_token_file",
]
