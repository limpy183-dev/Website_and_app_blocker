"""Smoke test: try to launch the GUI like `python -m focusfortress` and
print diagnostic information about the main window visibility."""
import os
import sys

os.environ["FOCUSFORTRESS_NO_ELEVATE"] = "1"

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from focusfortress.ui.theme import apply_theme
from focusfortress.engine import Engine
from focusfortress.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FocusFortress")
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)

    engine = Engine.instance()
    engine.start()

    win = MainWindow(engine=engine)
    win.resize(1240, 800)
    win.show()

    def report():
        print("isVisible:", win.isVisible())
        print("isMinimized:", win.isMinimized())
        print("isActiveWindow:", win.isActiveWindow())
        print("geometry:", win.geometry())
        print("windowState:", win.windowState().value)
        print("stack.count:", win.stack.count())
        print("stack.currentIndex:", win.stack.currentIndex())
        print("central size:", win.centralWidget().size())
        app.quit()

    QTimer.singleShot(500, report)
    rc = app.exec()
    engine.shutdown()
    return rc


if __name__ == "__main__":
    sys.exit(main())
