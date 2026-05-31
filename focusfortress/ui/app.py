"""PyQt6 application bootstrap with system-tray integration."""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from ..autostart import set_autostart
from ..engine import Engine
from ..stats import StatsTracker
from .main_window import MainWindow
from .theme import apply_theme


def run_gui(background: bool = False) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("FocusFortress")
    app.setOrganizationName("FocusFortress")
    # Keep the app alive even when the last window is closed.
    app.setQuitOnLastWindowClosed(False)

    apply_theme(app)

    engine = Engine.instance()
    engine.start()

    # Ensure the Windows autostart scheduled task matches the config.
    try:
        set_autostart(engine.config.settings.start_with_windows)
    except Exception:
        pass

    stats = StatsTracker(poll_seconds=5.0)
    stats.start()

    win = MainWindow(engine=engine)
    win.resize(1240, 800)

    # Only show the UI if not launched in background mode.
    if not background:
        win.show()

    rc = app.exec()
    engine.shutdown()
    stats.stop()
    return rc
