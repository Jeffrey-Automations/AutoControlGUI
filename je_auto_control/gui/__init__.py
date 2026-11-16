"""GUI package — kept import-light so individual tabs can be loaded without
pulling in the full main window (which transitively requires the optional
``webrtc`` extra). The launcher imports its dependencies lazily inside
:func:`start_autocontrol_gui` so::

    from je_auto_control.gui.profiler_tab import ProfilerTab

works in environments that have not installed PyAV / aiortc.
"""


def start_autocontrol_gui() -> None:
    """Open the AutoControl GUI; pulls in PySide6 + WebRTC stack lazily.

    While the window runs, cyclic garbage is collected on the GUI thread only
    (:class:`~je_auto_control.gui._gui_thread_gc.GuiThreadCollector`), so a
    worker thread never reaches a Qt object PySide would then delete late.
    """
    import sys

    from PySide6.QtWidgets import QApplication

    from je_auto_control.gui import _gui_thread_gc
    from je_auto_control.gui.main_window import AutoControlGUIUI
    from je_auto_control.gui.theme import prepare_application

    app = QApplication(sys.argv)
    prepare_application(app)
    collector = _gui_thread_gc.GuiThreadCollector(app)
    app.aboutToQuit.connect(collector.stop)
    window = AutoControlGUIUI()
    window.show()
    sys.exit(app.exec())
