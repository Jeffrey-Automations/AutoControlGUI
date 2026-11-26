"""Mask secret arguments before an action is logged or recorded.

``AC_secret_init`` / ``AC_secret_unlock`` take the vault passphrase,
``AC_secret_set`` the secret itself and ``AC_write_secret`` the text it types;
every argument of those is masked. Any
other command has the arguments masked whose name says they are secret
(``password``, ``token``...), and the signing, encryption and JWT commands
their ``key`` -- elsewhere ``key`` is a keyboard key. The executor logs every
action list it runs and keys its result record by ``str(action)``, so these
values reached the log file and every caller of the record (REST, MCP, the
socket server, run history) in plain text. The walk is recursive because a
command nested in a block (``AC_loop``, ``AC_if``...) is logged with its
parent.

A *result* is masked by :func:`redact_result`, the one rule for what a
command answered: a field whose name is in :data:`SENSITIVE_ARGUMENT_NAMES`
is masked wherever it sits in the result, whatever the command. The executor
uses it for its result log and the Script Builder for its result pane, and
:func:`masked_fields` lists exactly what it masked, which is what the builder
offers once. A few commands answer a secret under an ordinary name;
:data:`RESULT_SECRETS` lists those fields, masked the same way
(``AC_resolve_ref``'s ``value`` and ``AC_resolve_refs``'s ``resolved``, which
may hold an ``env://`` credential).

Generated secret or identifier. A value is a secret when holding it is enough
to act: a bearer token (``AC_user_add``, ``AC_user_rotate_token``,
``AC_rest_api_start`` / ``AC_rest_api_status``), a signed JWT
(``AC_jwt_encode``), a lease token (``AC_lease_secret``, ``AC_lease_active``).
It is an identifier when the person who ran the command has to read it to go
on and it names a thing rather than opening it. :data:`RESULT_IDENTIFIERS`
lists those, per command and field, and it is the only exemption:
``AC_approval_request`` answers ``{"token": ...}``, the request id the maker
hands to the checker. The exemption is honoured only where a person is
reading their own run (``show_identifiers=True``, the builder's result pane);
the log masks an identifier like any other ``token``.
"""
import functools
import inspect
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, FrozenSet, List, Mapping, Optional, Tuple, Union

_VAULT_COMMAND_PREFIX = "AC_secret_"
#: Commands outside the vault whose every argument is a secret.
_ALL_SECRET_COMMANDS: FrozenSet[str] = frozenset({"AC_write_secret"})
_MASK = "***"

#: Argument names that hold a secret whatever the command.
SENSITIVE_ARGUMENT_NAMES: FrozenSet[str] = frozenset({
    "password", "passphrase", "token", "secret", "api_key", "private_key",
    "client_secret", "authorization", "access_token", "refresh_token",
    # The credential headers, which arrive as the keys of a ``headers`` dict.
    "proxy-authorization", "cookie", "set-cookie", "x-api-key", "x-auth-token",
})

#: Commands whose ``url`` argument is itself a credential: a Slack, Discord or
#: Teams webhook URL is the key that posts to the channel.
_URL_SECRET_COMMANDS: FrozenSet[str] = frozenset({"AC_notify_webhook"})

#: Commands whose ``key`` argument is a cryptographic key.
_KEYED_COMMANDS: FrozenSet[str] = frozenset({
    "AC_sign_action_file", "AC_verify_action_file", "AC_encrypt_action_file",
    "AC_decrypt_action_file", "AC_jwt_encode", "AC_jwt_decode",
})


def redact_actions(value: Any) -> Any:
    """Return a copy of ``value`` with every secret argument masked.

    Anything that is not an action keeps its shape; nothing is mutated.
    """
    if isinstance(value, dict):
        # By name at every depth: only top-level arguments were masked, so
        # {"smtp": {"password": ...}} and {"headers": {"Authorization": ...}}
        # reached the log and the run record.
        return {key: _MASK if str(key).lower() in SENSITIVE_ARGUMENT_NAMES else redact_actions(item)
                for key, item in value.items()}
    if not isinstance(value, list):
        return value
    if value and isinstance(value[0], str) and value[0].startswith("AC_"):
        return [value[0], *(_redact_argument(value[0], argument) for argument in value[1:])]
    return [redact_actions(item) for item in value]


#: Result fields with a secret-looking name that are identifiers: command -> field names.
RESULT_IDENTIFIERS: Mapping[str, FrozenSet[str]] = MappingProxyType({
    # The request id the maker gives the checker, who must be somebody else.
    "AC_approval_request": frozenset({"token"}),
})
#: Result fields with an ordinary name that hold a secret: command -> field names.
RESULT_SECRETS: Mapping[str, FrozenSet[str]] = MappingProxyType({
    "AC_resolve_ref": frozenset({"value"}),
    "AC_resolve_refs": frozenset({"resolved"}),
})
_NO_FIELDS: FrozenSet[str] = frozenset()
# A record key is "execute: " + str(action); the command is its first element.
_RECORD_COMMAND = re.compile(r"^(?:execute|dry-run): \['(AC_\w+)'")

FieldPath = Tuple[Union[str, int], ...]


@dataclass(frozen=True)
class MaskedField:
    """One value :func:`redact_result` masked: where it sits in the result, and the value.

    ``path`` is the keys and list indexes that lead to it. ``value`` is left
    out of the text form, so formatting or logging the object never prints it.
    """
    path: FieldPath
    value: Any = field(repr=False)


def record_command(key: Any) -> Optional[str]:
    """The command an execution-record key was written for, or ``None``."""
    match = _RECORD_COMMAND.match(key) if isinstance(key, str) else None
    return match.group(1) if match is not None else None


def redact_result(command: Optional[str], result: Any, *, show_identifiers: bool = False,
                  found: Optional[List[MaskedField]] = None) -> Any:
    """A copy of ``result``, what ``command`` answered, with every secret-named field masked.

    At any depth, for any command. A field holding ``None`` or ``""`` has
    nothing to hide and is kept. An execution record nested in the result is
    masked per command, and an action list in it as :func:`redact_actions`
    masks one. ``show_identifiers`` keeps the fields :data:`RESULT_IDENTIFIERS`
    lists for the command readable. Each value masked is appended to ``found``
    when one is given. ``result`` is not changed.
    """
    visible = RESULT_IDENTIFIERS.get(command or "", _NO_FIELDS) if show_identifiers else _NO_FIELDS
    return _redact_answer(command, result, visible, (), _Walk(show_identifiers, found))


def masked_fields(command: Optional[str], result: Any, *,
                  show_identifiers: bool = False) -> List[MaskedField]:
    """Exactly the values :func:`redact_result` masks in ``result``, in order."""
    found: List[MaskedField] = []
    redact_result(command, result, show_identifiers=show_identifiers, found=found)
    return found


class _Walk:
    """What one :func:`redact_result` call carries down the result."""

    __slots__ = ("show_identifiers", "found")

    def __init__(self, show_identifiers: bool, found: Optional[List[MaskedField]]) -> None:
        self.show_identifiers = show_identifiers
        self.found = found


def _redact_answer(command: Optional[str], value: Any, visible: FrozenSet[str], path: FieldPath,
                   walk: _Walk) -> Any:
    """What ``command`` answered: its :data:`RESULT_SECRETS` fields masked, the rest by name."""
    secret = RESULT_SECRETS.get(command or "", _NO_FIELDS)
    if not secret or not isinstance(value, dict):
        return _redact_value(value, visible, path, walk)
    return {key: _hide(item, path + (key,), walk) if key in secret
            else _redact_field(key, item, visible, path + (key,), walk)
            for key, item in value.items()}


def _redact_value(value: Any, visible: FrozenSet[str], path: FieldPath, walk: _Walk) -> Any:
    if isinstance(value, dict):
        return {key: _redact_field(key, item, visible, path + (key,), walk)
                for key, item in value.items()}
    if not isinstance(value, (list, tuple)):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str) and value[0].startswith("AC_"):
        return redact_actions(value)  # an action: its arguments, which are not result fields
    return [_redact_value(item, _NO_FIELDS, path + (index,), walk)
            for index, item in enumerate(value)]


def _redact_field(key: Any, item: Any, visible: FrozenSet[str], path: FieldPath, walk: _Walk) -> Any:
    nested = record_command(key)
    if nested is not None:  # a record inside the result: its own command's rule applies
        shown = RESULT_IDENTIFIERS.get(nested, _NO_FIELDS) if walk.show_identifiers else _NO_FIELDS
        return _redact_answer(nested, item, shown, path, walk)
    name = str(key).lower()
    if name not in SENSITIVE_ARGUMENT_NAMES or name in visible:
        return _redact_value(item, _NO_FIELDS, path, walk)
    return _hide(item, path, walk)


def _hide(item: Any, path: FieldPath, walk: _Walk) -> Any:
    """``***`` for a secret field, noted in ``walk.found``; an empty one has nothing to hide."""
    if item is None or (isinstance(item, str) and not item):
        return item
    if walk.found is not None:
        walk.found.append(MaskedField(path, item))
    return _MASK


def is_sensitive_argument(command: str, name: str) -> bool:
    """Whether argument ``name`` of ``command`` holds a secret."""
    lowered = str(name).lower()
    return lowered in SENSITIVE_ARGUMENT_NAMES or (
        lowered == "key" and command in _KEYED_COMMANDS) or (
        lowered == "url" and command in _URL_SECRET_COMMANDS)


def _redact_argument(command: str, argument: Any) -> Any:
    if command.startswith(_VAULT_COMMAND_PREFIX) or command in _ALL_SECRET_COMMANDS:
        return _mask(argument)
    if isinstance(argument, dict):
        return {name: _MASK if is_sensitive_argument(command, name) else redact_actions(item)
                for name, item in argument.items()}
    if isinstance(argument, list):
        # A positional list: the same rule, by the name of each position.
        names = positional_parameter_names(command)
        return [_MASK if index < len(names) and is_sensitive_argument(command, names[index])
                else redact_actions(item) for index, item in enumerate(argument)]
    return redact_actions(argument)


def positional_parameter_names(command: str) -> Tuple[str, ...]:
    """The parameter names of ``command``, in order; empty for one the executor does not know."""
    try:
        # pylint: disable-next=import-outside-toplevel  # reason: the executor imports this module
        from je_auto_control.utils.executor.action_executor import executor
    except ImportError:  # the executor is still loading, so it has run nothing
        return ()
    target = executor.event_dict.get(command)
    try:
        return _parameter_names(target)
    except TypeError:  # an unhashable callable: not cached
        return _parameter_names.__wrapped__(target)


@functools.lru_cache(maxsize=4096)
def _parameter_names(target: Optional[Callable[..., Any]]) -> Tuple[str, ...]:
    if target is None:
        return ()
    try:
        return tuple(inspect.signature(target).parameters)
    except (TypeError, ValueError):  # no signature to read
        return ()


def describe_action(action: Any) -> str:
    """``str()`` of ``action`` with secrets masked, for logs and record keys."""
    return str(redact_actions(action))


def _mask(argument: Any) -> Any:
    if isinstance(argument, dict):
        return dict.fromkeys(argument, _MASK)
    if isinstance(argument, list):
        return [_MASK for _ in argument]
    return _MASK
