"""Headless tests for the Set-of-Marks overlay (number elements for VLM
grounding). Pure stdlib + Pillow; no Qt imports, no live screen needed."""
import io

from types import SimpleNamespace

import je_auto_control as ac
from je_auto_control.utils.set_of_marks import (
    mark_click, mark_elements, render_marks, resolve_mark)


def test_mark_elements_numbers_and_centers():
    elements = [
        {"bbox": [0, 0, 100, 20], "role": "button", "text": "OK"},
        SimpleNamespace(bounds=[10, 40, 60, 20], role="edit", name="user"),
        {"bbox": [0, 0], "text": "bad"},          # invalid bounds -> skipped
    ]
    marks = mark_elements(elements)
    assert [m["id"] for m in marks] == [1, 2]
    assert marks[0]["center"] == [50, 10]
    assert marks[1]["role"] == "edit"
    assert marks[1]["text"] == "user"


def test_resolve_mark():
    marks = mark_elements([{"bbox": [0, 0, 10, 10]},
                           {"bbox": [0, 0, 20, 20]}])
    assert resolve_mark(marks, 2)["bbox"] == [0, 0, 20, 20]
    assert resolve_mark(marks, 99) is None


def test_render_marks_returns_png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (80, 60), (255, 255, 255)).save(buf, format="PNG")
    out = render_marks(buf.getvalue(),
                       [{"id": 1, "bbox": [5, 5, 30, 12], "center": [20, 11]}])
    assert out[:8] == b"\x89PNG\r\n\x1a\n"   # valid PNG signature
    assert len(out) > 0


def test_mark_click_uses_supplied_marks(monkeypatch):
    import je_auto_control.wrapper.auto_control_mouse as mouse
    calls = {}
    monkeypatch.setattr(mouse, "set_mouse_position",
                        lambda x, y: calls.setdefault("pos", (x, y)))
    monkeypatch.setattr(mouse, "click_mouse",
                        lambda btn, x, y: calls.setdefault("click", (x, y)))
    marks = [{"id": 7, "bbox": [0, 0, 40, 20], "center": [20, 10]}]
    assert mark_click(7, marks) is True
    assert calls["click"] == (20, 10)
    assert mark_click(99, marks) is False    # unknown id -> no click


def test_each_caller_clicks_its_own_marks(monkeypatch):
    import threading
    import je_auto_control.utils.accessibility.accessibility_api as a11y
    import je_auto_control.wrapper.auto_control_mouse as mouse
    from je_auto_control.utils.set_of_marks import last_marks, mark_screen
    elements = {"A": [{"bbox": [0, 0, 20, 20]}], "B": [{"bbox": [500, 500, 20, 20]}]}
    monkeypatch.setattr(a11y, "list_accessibility_elements", lambda app_name=None: elements[app_name])
    monkeypatch.setattr(mouse, "set_mouse_position", lambda x, y: None)
    clicks = []
    monkeypatch.setattr(mouse, "click_mouse", lambda btn, x, y: clicks.append((threading.current_thread().name, x, y)))
    marked, b_done = threading.Event(), threading.Event()

    def caller_a():
        mark_screen("A")
        marked.set()
        b_done.wait(5)
        mark_click(1)

    def caller_b():
        marked.wait(5)
        mark_screen("B")
        mark_click(1)
        b_done.set()

    threads = [threading.Thread(target=caller_a, name="A"), threading.Thread(target=caller_b, name="B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert sorted(clicks) == [("A", 10, 10), ("B", 510, 510)]
    # A caller that marked nothing still gets the newest marks, as before.
    assert last_marks()[0]["center"] == [510, 510]


# --- wiring ---------------------------------------------------------------

def test_wiring():
    known = ac.executor.known_commands()
    assert {"AC_mark_screen", "AC_mark_click"} <= known
    from je_auto_control.utils.mcp_server.tools import (
        build_default_tool_registry)
    names = {t.name for t in build_default_tool_registry()}
    assert {"ac_mark_screen", "ac_mark_click"} <= names
    from je_auto_control.gui.script_builder.command_schema import _build_specs
    cmds = {s.command for s in _build_specs()}
    assert {"AC_mark_screen", "AC_mark_click"} <= cmds


def test_facade_exports():
    for attr in ("mark_elements", "resolve_mark", "render_marks",
                 "mark_screen", "mark_click"):
        assert hasattr(ac, attr)
        assert attr in ac.__all__
