# Draft report for Qt for Python: abort in `QObject::~QObject` from `BindingManager::runDeletionInMainThread`

Status: **draft, not filed.** The maintainer files it at <https://bugreports.qt.io> (project PYSIDE).
The evidence below was collected in this repository between 2026-11-15 and 2026-11-16. The records are
U-20261116-01 through -06 in `docs/updates/2026-11-b.md`, and the open item is in `Progress.md`.

---

**Title:** Windows: interpreter aborts in `QObject::~QObject` when a widget collected by a non-GUI thread's GC is deleted by `runDeletionInMainThread` (6.12.0)

**Component:** Shiboken / PySide6 object lifetime (deferred deletion, the PYSIDE-3288 change in 6.11.1)

**Environment**

- PySide6 / shiboken6 **6.12.0** (wheels from PyPI)
- Windows Server 2022 (GitHub-hosted `windows-2022`) and Windows 11 Pro 10.0.26200
- CPython **3.12.10**, **3.14.7** and **3.14.10**, x64. CPython 3.11 had aborted the same way earlier.
- `QT_QPA_PLATFORM=offscreen`

**What happens**

Our headless test suite (~19,000 tests, several hundred of which build widgets) intermittently dies with
`Fatal Python error: Aborted` (exit code 3). faulthandler marks the **main thread** as the one that
called `abort()`. Its Python frame is at a blocking call: `time.sleep`, a `threading.Event.wait`, or
`QApplication.processEvents`. Other threads are Python workers running ordinary Python code
(logging, a test-only script executor). Qt prints no fatal message.

It is intermittent in CI: 3 of 5 consecutive Windows runs aborted, on 3.12 and on 3.14. Locally it was
reliable when the same module order ran. It never reproduced from a single module or from any half of
that order.

In several of the aborts, Qt's last message before the abort was:

```
QThreadStorage: entry 0 destroyed before end of thread 0x...
```

This line never appeared in passing runs.

**Native stack of the aborting (main) thread**

The stack came from a minidump written by a `SIGABRT` handler. These are return addresses found by
scanning the stack, each named by the nearest export, innermost first:

```
ucrtbase!raise
ucrtbase!abort
Qt6Core!QObject::~QObject                       (??1QObject@@UEAA@XZ + 0x836)
shiboken6!<internal>
shiboken6!Shiboken::BindingManager::runDeletionInMainThread
python314!...                                   (pending call / eval breaker)
```

**State of the object being destroyed**

The object was read from the dump: its `QObject` pointer, then its `QObjectData`.

- The vtable pointer is already `QObject`'s, which is normal partway through a destructor chain. The
  second vtable is QPaintDevice's, so the object is a `QWidget`.
- `q_ptr` points back at the object. `parent` = null. `children` is empty.
- Flags: `wasDeleted = 1`, `wasWidget = 1`, `willBeWidget = 1`, `isWindow = 0`, `deleteLaterCalled = 0`.
- `postedEvents = 0`, `metaObject = null`.

So a top-level widget that Python owned was being deleted by the deferred-deletion queue on the main
thread when `~QObject` called `abort()`.

**How the widgets reach that path**

The tests create top-level `QWidget`s, and tab widgets built on them, without parents. Some of them
end up in reference cycles, so only the cyclic GC frees them. Meanwhile the test runs long Python work
on plain `threading.Thread` workers. That work emits Qt signals to GUI-thread objects, which makes the
workers Qt-adopted threads. Whichever thread allocates when a collection is due runs it, so a worker
collects the leaked widgets. Since 6.11.1 shiboken does not delete those on the worker; it queues them
and deletes them later on the main thread.

**What did not reproduce it** (each run hundreds to thousands of times)

- Cyclic, Python-owned widgets, with a layout, children and a running child `QTimer`, created on the main
  thread, collected by `gc.collect()` on a worker, followed by `processEvents()` on the main thread.
- The same with widgets that had `deleteLater()` pending, or already flushed, before the worker
  collected them.
- Worker threads that call `QThread.currentThread()`, keep the wrapper, and emit to a GUI-thread
  object before exiting.

**Workaround that removes it**

The workaround is to pause automatic collection (`gc.disable()`) while widgets and worker threads
coexist, and run `gc.collect()` on the main thread at a safe point.

- With it, the full Windows matrix (3.11 to 3.14) passed, and the local order that aborted 3 of 3
  times passed 8,856 tests.
- Collecting on the main thread after every test also removed the abort, but it was too slow for CI.

**Questions for the maintainers**

1. Can a pointer queued for `runDeletionInMainThread` be destroyed by Qt before the queue runs, so the
   queued delete runs on freed or reused memory? The `QThreadStorage` warning and an abort with no message
   suggest corruption rather than a `qFatal`.
2. Is deferring a top-level `QWidget`'s deletion from an adopted non-GUI thread expected to be safe? Or
   should applications keep the collector off non-GUI threads, as above?
