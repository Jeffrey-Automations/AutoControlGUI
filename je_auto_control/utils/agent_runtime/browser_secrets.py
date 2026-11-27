"""Keep text a page marks `data-secret` out of a browser observation.

The SDK may take the page text and the element names straight from the rendered page. Through its
public ``visible`` this asks whether each document shows marked text, before and after the
observation. A marked document loses its page text, since its parts cannot be told apart here, and
the name of every element in, around or containing a marked one; when the mark came or went around
the observation, what it touched is unknown and every name goes. A page with frames is observed
twice, because its frames are only known after the first. A label outside the marked element is not
covered.
"""
from __future__ import annotations

from typing import Any

from je_auto_control.utils.agent_runtime.models import detached

_FIRST = " >> visible=true >> nth=0"  # at most one match: the SDK treats several as an error
_MARKED = "[data-secret]" + _FIRST


def _shown(session: Any, selector: str, frame: str) -> bool:
    return session.visible(selector, frame) is not False


def _documents(raw: dict[str, Any]) -> set[str]:
    """The readable documents of an observation: ``""`` for the main page, a selector per frame."""
    return {""} | {frame["selector"] for frame in raw.get("frames", []) if "elements" in frame}


def _marked(session: Any, documents: set[str]) -> set[str]:
    return {frame for frame in sorted(documents) if _shown(session, _MARKED, frame)}


def _touches(session: Any, selector: str, frame: str) -> bool:
    inside = f":is({selector}):is([data-secret], [data-secret] *, :has([data-secret]))"
    return _shown(session, inside + _FIRST, frame)


def _redact(session: Any, raw: dict[str, Any], steady: set[str], unsteady: set[str]) -> None:
    documents = [("", raw)] + [(frame["selector"], frame) for frame in raw.get("frames", [])]
    for frame, document in documents:
        if frame not in steady | unsteady:
            continue
        document["text"] = ""
        for element in document.get("elements", []):
            if element.get("text") and (frame in unsteady or _touches(session, element["selector"], frame)):
                element["text"] = ""


def observe_unmarked(session: Any) -> dict[str, Any]:
    """Observe, then withhold the text of every document that showed marked text around it."""
    before = _marked(session, {""})
    raw: dict[str, Any] = detached(session.observe())
    known = {""}
    if len(_documents(raw)) > 1:
        known = _documents(raw)
        before |= _marked(session, known)
        raw = detached(session.observe())
    current = _documents(raw)
    after = _marked(session, current)
    unsteady = (before ^ after) & current | (current - known)
    _redact(session, raw, (before & after) - unsteady, unsteady)
    return raw


__all__ = ["observe_unmarked"]
