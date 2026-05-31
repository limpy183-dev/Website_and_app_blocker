"""Modal countdown dialog for the Advanced settings cooldown lock.

While the timer is running, the only useful action is closing the popup
(the inputs behind it remain locked).  When the timer reaches zero the
primary button activates and the user can confirm to "Unlock now",
returning ``QDialog.Accepted``.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from .. import cooldown
from .theme import Colors


class CooldownDialog(QDialog):
    """Always-modal popup that mirrors the live cooldown remaining.

    The dialog can be opened multiple times - it always reflects the same
    persistent timer.  Accepts only when the timer hits 0 AND the user
    explicitly clicks the unlock button.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Advanced settings locked")
        self.setModal(True)
        # Make sure the user cannot dismiss with Esc accidentally and lose
        # context - we still allow Close, but only via the explicit button.
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(440)

        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 22)
        v.setSpacing(14)

        title = QLabel("Advanced settings are locked")
        tf = QFont(); tf.setPointSize(14); tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color:{Colors.TEXT};")
        v.addWidget(title)

        body = QLabel(
            "To prevent impulsive changes, modifications to the Advanced "
            "tab are gated by a one-hour cooldown.\n\n"
            "When the timer below reaches 00:00:00 you will be allowed to "
            "make a single editing session.  The wait restarts each time "
            "you save."
        )
        body.setWordWrap(True)
        body.setStyleSheet(f"color:{Colors.TEXT_MUTED}; font-size:12.5px;")
        v.addWidget(body)

        self._timer_lbl = QLabel("01:00:00")
        self._timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        big = QFont("Cascadia Mono"); big.setPointSize(40); big.setBold(True)
        self._timer_lbl.setFont(big)
        self._timer_lbl.setStyleSheet(
            f"color:{Colors.ACCENT};"
            f"background:{Colors.SURFACE};"
            f"border:1px solid {Colors.BORDER};"
            f"border-radius:14px; padding:18px 0;"
            f"letter-spacing:2px;"
        )
        self._timer_lbl.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Fixed)
        v.addWidget(self._timer_lbl)

        self._hint = QLabel(
            "Closing this window will not cancel the timer."
        )
        self._hint.setWordWrap(True)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet(
            f"color:{Colors.TEXT_FAINT}; font-size:11px;"
        )
        v.addWidget(self._hint)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._close_btn = QPushButton("Close")
        self._close_btn.setProperty("variant", "ghost")
        self._close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._close_btn)

        self._unlock_btn = QPushButton("Unlock now")
        self._unlock_btn.setProperty("variant", "primary")
        self._unlock_btn.setEnabled(False)
        self._unlock_btn.clicked.connect(self._on_unlock)
        btn_row.addWidget(self._unlock_btn)
        v.addLayout(btn_row)

        # Update once a second.  We use a QTimer rather than running a
        # blocking loop so the dialog stays responsive.
        self._tick = QTimer(self)
        self._tick.setInterval(500)
        self._tick.timeout.connect(self._refresh)
        self._tick.start()
        self._refresh()

    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        rem = cooldown.remaining_seconds()
        self._timer_lbl.setText(cooldown.format_remaining(rem))
        if rem <= 0:
            self._unlock_btn.setEnabled(True)
            self._timer_lbl.setStyleSheet(
                f"color:{Colors.SUCCESS};"
                f"background:{Colors.SURFACE};"
                f"border:1px solid {Colors.BORDER};"
                f"border-radius:14px; padding:18px 0;"
                f"letter-spacing:2px;"
            )
            self._hint.setText("Cooldown complete. You may unlock and edit.")
        else:
            self._unlock_btn.setEnabled(False)

    def _on_unlock(self) -> None:
        if cooldown.mark_unlocked():
            self.accept()

    # Block Esc-to-close so the user can't dismiss it instantly without
    # reading the message.  They must click the explicit Close button.
    def keyPressEvent(self, ev) -> None:  # type: ignore[override]
        if ev.key() == Qt.Key.Key_Escape:
            ev.ignore()
            return
        super().keyPressEvent(ev)
