"""Decide which open documents are AutoControl action files.

An editor client hands the server every document its selector matches;
diagnosing all of them as action lists turned an ordinary
``package.json`` into "root must be a list" and a commented JSONC
settings file into parse errors. Only URIs matching the configured
action-file globs are diagnosed. The VS Code client sends its
``autocontrolLsp.actionFiles`` setting as the ``actionFiles``
initialization option; a client that sends none gets
:data:`DEFAULT_ACTION_FILE_GLOBS`, the same default the extension ships.

Globs follow the VS Code subset: ``**`` crosses directories, ``*`` and
``?`` stay inside one path segment, ``{a,b}`` is an alternation. They
are matched against the document's absolute path, so a pattern that
should match anywhere starts with ``**/``.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional, Pattern, Tuple
from urllib.parse import unquote, urlparse

DEFAULT_ACTION_FILE_GLOBS: Tuple[str, ...] = (
    "**/*.ac.json",
    "**/actions/**/*.json",
)

_TOKEN = re.compile(r"\*\*/|\*\*|\*|\?|\{[^{}]*\}|[^*?{]+|\{")
_DRIVE_PATH = re.compile(r"^/[A-Za-z]:")
_SIMPLE_TOKENS = {"**/": "(?:.*/)?", "**": ".*", "*": "[^/]*", "?": "[^/]"}


def _translate(glob: str) -> str:
    """Regex source for ``glob``; a brace group's options are globs too."""
    parts = []
    for token in _TOKEN.findall(glob):
        if token in _SIMPLE_TOKENS:
            parts.append(_SIMPLE_TOKENS[token])
        elif len(token) > 1 and token.startswith("{") and token.endswith("}"):
            options = token[1:-1].split(",")
            parts.append("(?:" + "|".join(_translate(o) for o in options) + ")")
        else:
            parts.append(re.escape(token))
    return "".join(parts)


def glob_to_regex(glob: str) -> Pattern[str]:
    """Compile a VS Code style glob into a regex for :meth:`re.Pattern.fullmatch`."""
    return re.compile(_translate(glob.replace("\\", "/")), re.DOTALL)


def uri_to_path(uri: str) -> Optional[str]:
    """The ``/``-separated path of a ``file:`` URI, or ``None`` for any other scheme."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path = unquote(parsed.path)
    if parsed.netloc:
        return f"//{parsed.netloc}{path}"
    # file:///c%3A/work/x.json -> c:/work/x.json, so an absolute glob can match.
    return path[1:] if _DRIVE_PATH.match(path) else path


class ActionFileFilter:
    """Match document URIs against the configured action-file globs."""

    def __init__(self, globs: Optional[Iterable[str]] = None) -> None:
        self._globs = tuple(DEFAULT_ACTION_FILE_GLOBS if globs is None else globs)
        self._patterns = tuple(glob_to_regex(glob) for glob in self._globs)

    @property
    def globs(self) -> Tuple[str, ...]:
        """The globs in effect."""
        return self._globs

    @classmethod
    def from_initialize_params(cls, params: Dict[str, Any]) -> "ActionFileFilter":
        """Read ``initializationOptions.actionFiles``; fall back to the defaults."""
        options = params.get("initializationOptions")
        globs = options.get("actionFiles") if isinstance(options, dict) else None
        if isinstance(globs, list) and all(isinstance(glob, str) for glob in globs):
            return cls(globs)
        return cls()

    def matches(self, uri: Any) -> bool:
        """Whether the document at ``uri`` is an action file."""
        path = uri_to_path(uri) if isinstance(uri, str) else None
        if path is None:
            return False
        # Windows paths compare without case, as the file system does.
        flags = re.IGNORECASE if re.match(r"^[A-Za-z]:/", path) else 0
        return any(re.fullmatch(pattern.pattern, path, pattern.flags | flags)
                   for pattern in self._patterns)


__all__ = [
    "ActionFileFilter", "DEFAULT_ACTION_FILE_GLOBS", "glob_to_regex",
    "uri_to_path",
]
