"""GUI objects release what they registered (offscreen, fakes only).

``LanBrowseDialog`` stopped its zeroconf browser only in ``closeEvent``, which
``accept()`` / ``reject()`` never reach; ``PresenceTab`` never removed its
registry listener, so the registry kept calling a deleted widget.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Browser:
    instances = []

    def __init__(self, on_change):
        self.on_change = on_change
        self.stopped = False
        _Browser.instances.append(self)

    def stop(self):
        self.stopped = True


@pytest.mark.parametrize("ending", ["accept", "reject"])
def test_the_lan_browser_stops_however_the_dialog_ends(qapp, monkeypatch, ending):
    from je_auto_control.utils.remote_desktop import lan_discovery
    from je_auto_control.gui.remote_desktop.webrtc_dialogs import LanBrowseDialog
    monkeypatch.setattr(lan_discovery, "HostBrowser", _Browser)
    monkeypatch.setattr(lan_discovery, "is_discovery_available", lambda: True)
    _Browser.instances.clear()
    dialog = LanBrowseDialog()
    getattr(dialog, ending)()
    assert _Browser.instances
    dialog.deleteLater()
    # Closing joins zeroconf's thread, so it runs on a worker -- even once the dialog is gone.
    from headless._qt_settle import pump_until
    assert pump_until(lambda: _Browser.instances[0].stopped)


def test_the_lan_browser_neither_keeps_the_dialog_alive_nor_loses_a_failed_stop(qapp, monkeypatch):
    import gc
    import weakref
    from headless._qt_settle import pump_until
    from je_auto_control.gui._stop_custody import stop_custody
    from je_auto_control.utils.remote_desktop import lan_discovery
    from je_auto_control.gui.remote_desktop.webrtc_dialogs import LanBrowseDialog

    class _Stuck(_Browser):
        def stop(self):
            raise RuntimeError("media retirement incomplete: zeroconf close")

    custody = stop_custody()
    for record in custody.snapshot():
        custody.forget(record.stop_id)
    monkeypatch.setattr(lan_discovery, "HostBrowser", _Stuck)
    monkeypatch.setattr(lan_discovery, "is_discovery_available", lambda: True)
    _Browser.instances.clear()
    dialog = LanBrowseDialog()
    reference = weakref.ref(dialog)
    browser = _Browser.instances[0]
    dialog.reject()
    dialog.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    del dialog
    gc.collect()
    assert reference() is None                       # the browser's callback did not hold it
    browser.on_change({"late": {"host_id": "late"}})  # a report after the dialog is gone: dropped
    assert pump_until(lambda: bool(custody.snapshot()))
    assert "zeroconf close" in custody.snapshot()[0].error
    for record in custody.snapshot():
        custody.forget(record.stop_id)


def test_a_destroyed_presence_tab_leaves_the_registry(qapp, monkeypatch):
    from je_auto_control.gui import presence_tab as tab_mod
    from je_auto_control.utils.remote_desktop.presence import PresenceRegistry
    registry = PresenceRegistry()
    monkeypatch.setattr(tab_mod, "default_presence_registry", lambda: registry)
    tab = tab_mod.PresenceTab()
    assert len(registry._listeners) == 1  # noqa: SLF001
    tab.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert registry._listeners == []  # noqa: SLF001
