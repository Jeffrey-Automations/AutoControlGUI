"""Shared teardown for the headless suite."""
import gc
import os
import re
import sys

import pytest


def _live_qt_application():
    """The running QApplication, or None.

    Looks in ``sys.modules`` rather than importing PySide6: most of this suite
    is Qt-free, and importing Qt to ask whether Qt is in use would load it into
    every one of those runs.
    """
    widgets = sys.modules.get("PySide6.QtWidgets")
    if widgets is None:
        return None
    return widgets.QApplication.instance()


_QT_EVIDENCE_DIR = "AUTOCONTROL_NATIVE_ARTIFACT_DIR"
_qt_log = []


def _record_qt_messages():
    """In CI, append Qt's own messages to ``qt-messages.log`` in the native artifact folder.

    A ``qFatal`` aborts the interpreter right after Qt prints its reason to
    stderr, and pytest's fd capture holds that stderr until the test ends --
    which it never does. Windows 3.14 has lost the reason that way
    ("Fatal Python error: Aborted" and nothing else, in
    ``test_gui_script_runs.py``). Qt calls the handler before it aborts, and
    each line is written and closed at once, so the reason survives the
    process. Installed once, the first time a test finds Qt loaded, and only
    when ``scripts/ci_native_diagnostics.py`` names the folder.
    """
    folder = os.environ.get(_QT_EVIDENCE_DIR)
    if _qt_log or not folder:
        return
    core = sys.modules.get("PySide6.QtCore")
    if core is None:
        return
    path = os.path.join(folder, "qt-messages.log")
    _qt_log.append(path)

    def handler(mode, _context, message):
        test = os.environ.get("PYTEST_CURRENT_TEST", "")
        try:
            with open(path, "a", encoding="utf-8") as log:
                log.write(f"{getattr(mode, 'name', mode)} [{test}] {message}\n")
        except OSError:
            return

    core.qInstallMessageHandler(handler)


_QT_IMPORT = re.compile(r"^\s*(?:from|import)\s+(?:PySide6|je_auto_control\.gui)\b"
                        r"|importorskip\(\s*['\"]PySide6", re.MULTILINE)
_qt_modules: dict = {}


def _module_uses_qt(module) -> bool:
    """Whether a test module imports Qt or the GUI package anywhere (lazily, too); read once per file."""
    path = getattr(module, "__file__", None)
    if path is None:
        return False
    if path not in _qt_modules:
        try:
            with open(path, encoding="utf-8") as source:
                _qt_modules[path] = bool(_QT_IMPORT.search(source.read()))
        except OSError:
            _qt_modules[path] = False
    return _qt_modules[path]


@pytest.fixture(autouse=True, scope="module")
def no_worker_collects_qt_garbage(request):
    """In a module that uses Qt, pause automatic collection; collect once, on the main thread, at its end.

    Cyclic garbage is collected by whichever thread happens to allocate when
    the collector runs. A Python-owned Qt object collected on a worker thread
    is not deleted there: PySide 6.12 queues it and deletes it later on the
    main thread (``Shiboken::BindingManager::runDeletionInMainThread``), and on
    Windows one such deferred delete of a leaked top-level ``QWidget`` aborted
    the interpreter inside ``QObject::~QObject`` -- a minidump showed that frame,
    the object's ``wasWidget`` / ``wasDeleted`` bits and no Qt message. It hit
    3.14 in ``test_gui_script_runs.py`` and 3.12 (and, earlier, 3.11) in
    ``test_gui_offthread_sites.py``, each time after a ``QThreadStorage: entry 0
    destroyed before end of thread`` warning.

    With automatic collection paused no worker can start a collection at all;
    an explicit ``gc.collect()`` still works, and tests that pause it
    themselves restore what they found. The module's garbage is collected here
    instead, on the main thread, and any deletes that queues are flushed.
    Collecting after every test instead cost about 0.4 s a test on CI and
    pushed the Windows jobs past their 120-minute limit; this is one
    collection per module.
    """
    if not _module_uses_qt(request.module):
        yield
        return
    paused = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if paused:
            gc.enable()
        gc.collect()
        app = _live_qt_application()
        if app is not None:
            from PySide6.QtCore import QCoreApplication, QEvent
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()


@pytest.fixture(autouse=True)
def flush_qt_deferred_deletes():
    """Run Qt's queued ``deleteLater()`` work at the end of every test.

    ``deleteLater()`` does nothing until an event loop runs, and almost no GUI
    test module here runs one. Left queued, a widget — and any helper thread or
    timer it started at construction — survives until some *later* test pumps
    events, and is then destroyed inside that unrelated test.

    That is not hypothetical: seven ``AdminConsoleTab``s queued by
    ``test_admin_console_thumbnails_gui.py`` were destroyed inside the nested
    modal ``exec()`` of ``test_usb_acl_prompt.py``, killing the interpreter with
    rc 3221226505 (0xC0000409, a ``__fastfail``). There was no traceback,
    faulthandler could not see it, and the ~500 tests after it never ran.

    Flushing here makes each test clean up after itself, so no test module has
    to remember. Being autouse, this is set up before any test-local fixture
    and therefore torn down *after* it — the module's own ``deleteLater()``
    calls have already been made by the time this runs.

    """
    _record_qt_messages()
    yield
    app = _live_qt_application()
    if app is None:
        return
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


# Backend calls that move the pointer or type on the real desktop.
_INPUT_CALLS = frozenset({
    "mouse_event", "set_position", "press_mouse", "release_mouse", "click_mouse", "scroll",
    "send_mouse_event_to_window", "press_key", "release_key", "press_unicode",
    "release_unicode", "type_unicode_unit", "send_key_event_to_window",
})


class _RecordingBackend:
    """The platform backend with every input call recorded instead of performed."""

    def __init__(self, real, calls):
        self._real = real
        self._calls = calls

    def __getattr__(self, name):
        attribute = getattr(self._real, name)
        if name not in _INPUT_CALLS or not callable(attribute):
            return attribute

        def record(*args, **kwargs):
            self._calls.append((name, args))

        return record


@pytest.fixture(autouse=True)
def refuse_real_input(monkeypatch):
    """Fail a test whose input reaches the real mouse or keyboard backend.

    A test that faked ``press_mouse`` but not ``set_mouse_position`` moved
    the real cursor on every run -- on a desktop where another program may be
    typing. Every test sees the backends through a recorder instead: a call
    that reaches it does nothing, and the test fails naming it, so the fake
    that is missing gets added. Tests that install their own backend fake
    replace the recorder and are unaffected.
    """
    wrappers = sys.modules.get("je_auto_control.wrapper.platform_wrapper")
    if wrappers is None:
        yield
        return
    from je_auto_control.wrapper import auto_control_keyboard, auto_control_mouse
    calls = []
    mouse = _RecordingBackend(wrappers.mouse, calls)
    keyboard = _RecordingBackend(wrappers.keyboard, calls)
    for module, name, guard in ((wrappers, "mouse", mouse), (wrappers, "keyboard", keyboard),
                                (auto_control_mouse, "mouse", mouse),
                                (auto_control_keyboard, "keyboard", keyboard)):
        monkeypatch.setattr(module, name, guard)
    yield
    if calls:
        pytest.fail(f"the test reached the real input backend: {calls[:5]}", pytrace=False)
