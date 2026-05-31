"""Customise the block page."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
    QWidget,
)

from ...engine import Engine
from ..common import info
from ..theme import Colors
from ..widgets import Card, PageHeader


class BlockPageTab(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        self.header = PageHeader(
            "Block Page",
            "Customise the page users see when they try to visit a blocked site."
        )
        save = QPushButton("Save")
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save)
        self.header.add_action(save)
        v.addWidget(self.header)

        # Quote card
        quote_card = Card(
            "Motivational quote",
            "Shown on the default block page.",
        )
        self.quote = QLineEdit()
        self.quote.setPlaceholderText("e.g. Discipline is choosing between what you want now and what you want most.")
        quote_card.addWidget(self.quote)
        v.addWidget(quote_card)

        # HTML card
        html_card = Card(
            "Custom HTML (optional)",
            "Leave blank to use the default design.",
        )
        self.html = QPlainTextEdit()
        self.html.setPlaceholderText("<html><body>...</body></html>")
        html_card.addWidget(self.html, 1)
        v.addWidget(html_card, 1)

        self._reload()

    def showEvent(self, e):
        self._reload(); super().showEvent(e)

    def _reload(self) -> None:
        s = self.engine.config.settings
        self.quote.setText(s.motivational_quote)
        self.html.setPlainText(s.custom_block_page_html)

    def _save(self) -> None:
        s = self.engine.config.settings
        s.motivational_quote = self.quote.text()
        s.custom_block_page_html = self.html.toPlainText()
        self.engine.save()
        try:
            self.engine._apply()
        except Exception:
            pass
        info(self, "Block page saved.")
