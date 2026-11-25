"""Keep text a page marks `data-secret` out of a browser observation.

The SDK refuses such text in its explicit reads, but the page text and the element names of its
``observe`` come straight from the rendered page. Through the same SDK's public ``visible`` this
asks whether a document shows marked text, before and after the observation. If it does, the page
text is withheld, since its parts cannot be told apart here, and so is the name of every element
in, around or containing a marked one. A label outside the marked element is not covered.
"""
from __future__ import annotations

from typing import Any

_FIRST = " >> visible=true >> nth=0"  # at most one match: the SDK treats several as an error
_MARKED = "[data-secret]" + _FIRST


def _shown(session: Any, selector: str, frame: str) -> bool:
    return session.visible(selector, frame) is not False


def marked_documents(session: Any, raw: dict[str, Any]) -> set[str]:
    """The frame selectors (``""`` is the main page) whose document shows marked text."""
    frames = [""] + [frame["selector"] for frame in raw.get("frames", []) if "elements" in frame]
    return {frame for frame in frames if _shown(session, _MARKED, frame)}


def _touches(session: Any, selector: str, frame: str) -> bool:
    inside = f":is({selector}):is([data-secret], [data-secret] *, :has([data-secret]))"
    return _shown(session, inside + _FIRST, frame)


def redact_marked(session: Any, raw: dict[str, Any], marked: set[str]) -> None:
    """Withhold the page text and touched element names of every marked document, in place."""
    if "" in marked:
        raw["text"] = ""
    documents = [("", raw)] + [(frame["selector"], frame) for frame in raw.get("frames", [])]
    for frame, document in documents:
        if frame not in marked:
            continue
        for element in document.get("elements", []):
            if element.get("text") and _touches(session, element["selector"], frame):
                element["text"] = ""
        if frame:
            document["text"] = ""


__all__ = ["marked_documents", "redact_marked"]
