"""Frozen Turkey: force lock/logoff/shutdown on a schedule."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTime
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton,
    QTimeEdit, QVBoxLayout, QWidget,
)

from ...engine import Engine
from ..common import info
from ..theme import Colors
from ..widgets import Card, PageHeader

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class FrozenTurkeyTab(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        self.header = PageHeader(
            "Frozen Turkey",
            "At the configured start time the computer will automatically "
            "lock, log off, or shut down every selected day."
        )
        save = QPushButton("Save")
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save)
        self.header.add_action(save)
        v.addWidget(self.header)

        # Settings card
        settings = Card("Action & window", "Choose what happens and when.")
        self.enabled = QCheckBox("Enable frozen turkey")
        settings.addWidget(self.enabled)

        f = QFormLayout()
        f.setSpacing(12)
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.action = QComboBox()
        self.action.addItems(["lock", "logoff", "shutdown"])
        self.start = QTimeEdit()
        self.end = QTimeEdit()
        f.addRow("Action:", self.action)
        f.addRow("Start:", self.start)
        f.addRow("End:", self.end)
        settings.addLayout(f)
        v.addWidget(settings)

        # Days card
        days_card = Card("Days", "Pick the days this rule applies.")
        day_row = QHBoxLayout()
        day_row.setSpacing(10)
        self.day_boxes = []
        for name in DAYS:
            cb = QCheckBox(name)
            day_row.addWidget(cb)
            self.day_boxes.append(cb)
        day_row.addStretch(1)
        days_card.addLayout(day_row)
        v.addWidget(days_card)

        warn = Card(
            "Heads up",
            "Shutdown/logoff can close unsaved work. Lock is usually the "
            "safest option while you build the habit.",
        )
        v.addWidget(warn)

        v.addStretch(1)
        self._reload()

    def showEvent(self, e):
        self._reload(); super().showEvent(e)

    def _reload(self) -> None:
        ft = self.engine.config.settings.frozen_turkey
        self.enabled.setChecked(ft.enabled)
        self.action.setCurrentText(ft.action)
        self.start.setTime(QTime.fromString(ft.start, "HH:mm"))
        self.end.setTime(QTime.fromString(ft.end, "HH:mm"))
        for i, cb in enumerate(self.day_boxes):
            cb.setChecked(i in ft.days)

    def _save(self) -> None:
        ft = self.engine.config.settings.frozen_turkey
        ft.enabled = self.enabled.isChecked()
        ft.action = self.action.currentText()
        ft.start = self.start.time().toString("HH:mm")
        ft.end = self.end.time().toString("HH:mm")
        ft.days = [i for i, cb in enumerate(self.day_boxes) if cb.isChecked()]
        self.engine.save()
        info(self, "Frozen Turkey settings saved.")
