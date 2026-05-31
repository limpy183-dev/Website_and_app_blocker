"""Cancellable countdown shown before a Frozen Turkey action (report §2.7).

The engine delegates to this via :meth:`Engine.set_frozen_action_handler`. The
dialog counts down and, if not cancelled, calls back into the engine to run the
action - giving the user a window to save work before a lock/logoff/shutdown.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from .theme import Colors

_ACTION_VERB = {
    "lock": "lock the computer",
    "logoff": "log you off",
    "shutdown": "shut the computer down",
}


class FrozenCountdownDialog(QDialog):
    """A modal-ish countdown with a Cancel button.

    On timeout it calls ``on_fire(action)``; on cancel it calls ``on_cancel()``.
    Each callback runs at most once.
    """

    def __init__(self, action: str, seconds: int, on_fire, on_cancel, parent=None) -> None:
        super().__init__(parent)
        self._action = action
        self._remaining = max(1, int(seconds))
        self._on_fire = on_fire
        self._on_cancel = on_cancel
        self._done = False

        self.setWindowTitle("Frozen Turkey")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
        )
        self.setMinimumWidth(440)

        v = QVBoxLayout(self)
        v.setContentsMargins(28, 26, 28, 22)
        v.setSpacing(16)

        head = QLabel("FROZEN TURKEY")
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.setStyleSheet(
            f"color:{Colors.WARNING};font-size:13px;font-weight:800;letter-spacing:2px;"
        )
        v.addWidget(head)

        verb = _ACTION_VERB.get(action, action)
        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._body.setStyleSheet(
            f"color:{Colors.TEXT};font-size:18px;font-weight:700;"
        )
        self._verb = verb
        v.addWidget(self._body)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setProperty("variant", "primary")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self._cancel)
        row.addWidget(cancel)
        row.addStretch(1)
        v.addLayout(row)

        self._update_text()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _update_text(self) -> None:
        self._body.setText(
            f"FocusFortress will {self._verb} in <b>{self._remaining}s</b>.<br>"
            "Save your work or cancel."
        )

    def _tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self._fire()
            return
        self._update_text()

    def _fire(self) -> None:
        if self._done:
            return
        self._done = True
        self._timer.stop()
        try:
            self._on_fire(self._action)
        finally:
            self.close()

    def _cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self._timer.stop()
        try:
            self._on_cancel()
        finally:
            self.close()

    # Esc cancels (never trap the user).
    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Closing the window (without Cancel/fire) counts as cancel - safer to
        # abort than to silently shut down.
        if not self._done:
            self._done = True
            self._timer.stop()
            try:
                self._on_cancel()
            except Exception:
                pass
        super().closeEvent(event)
