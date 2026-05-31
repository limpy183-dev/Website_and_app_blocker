"""Statistics tab: view, export, clear local usage stats."""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...config_store import clear_stats, load_stats
from ...engine import Engine
from ..common import confirm, info
from ..theme import Colors
from ..widgets import Card, PageHeader, StatCard


def _fmt(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


class StatsTab(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # Header
        self.header = PageHeader(
            "Statistics",
            "All data is stored locally. No telemetry, no accounts, no cloud."
        )
        refresh = QPushButton("Refresh")
        export = QPushButton("Export JSON")
        clear = QPushButton("Clear all")
        clear.setProperty("variant", "danger")
        refresh.clicked.connect(self._reload)
        export.clicked.connect(self._export)
        clear.clicked.connect(self._clear)
        self.header.add_action(refresh)
        self.header.add_action(export)
        self.header.add_action(clear)
        v.addWidget(self.header)

        # Summary stat cards
        summary_row = QHBoxLayout()
        summary_row.setSpacing(14)
        self.card_total = StatCard("TOTAL TIME TRACKED",   "-", Colors.ACCENT_HOV)
        self.card_apps  = StatCard("APPLICATIONS TRACKED", "-", Colors.SUCCESS)
        self.card_sites = StatCard("WEBSITES TRACKED",     "-", Colors.INFO)
        self.card_top   = StatCard("TOP WEBSITE",          "-")
        summary_row.addWidget(self.card_total)
        summary_row.addWidget(self.card_apps)
        summary_row.addWidget(self.card_sites)
        summary_row.addWidget(self.card_top)
        v.addLayout(summary_row)

        # Tables
        tables_row = QHBoxLayout()
        tables_row.setSpacing(14)

        app_card = Card("Applications", "Time spent per executable / process")
        self.app_table = self._mk_table(["Application", "Time"])
        app_card.addWidget(self.app_table, 1)
        tables_row.addWidget(app_card, 1)

        site_card = Card("Websites", "Time spent per domain (proxy + title heuristic)")
        self.site_table = self._mk_table(["Website", "Time"])
        site_card.addWidget(self.site_table, 1)
        tables_row.addWidget(site_card, 1)

        v.addLayout(tables_row, 1)

        self._reload()

    def _mk_table(self, cols) -> QTableWidget:
        t = QTableWidget(0, len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setShowGrid(False)
        t.setAlternatingRowColors(False)
        return t

    def showEvent(self, e):
        self._reload(); super().showEvent(e)

    def _reload(self) -> None:
        s = load_stats()
        apps = sorted(s.get("apps", {}).items(), key=lambda kv: kv[1], reverse=True)
        sites = sorted(s.get("sites", {}).items(), key=lambda kv: kv[1], reverse=True)
        self._populate(self.app_table, apps)
        self._populate(self.site_table, sites)

        total = sum(v for _, v in apps) + sum(v for _, v in sites)
        self.card_total.set_value(_fmt(total))
        self.card_apps.set_value(str(len(apps)))
        self.card_sites.set_value(str(len(sites)))
        self.card_top.set_value(sites[0][0] if sites else "-")

    def _populate(self, table: QTableWidget, rows) -> None:
        table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            a = QTableWidgetItem(str(k))
            b = QTableWidgetItem(_fmt(float(v)))
            b.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(i, 0, a)
            table.setItem(i, 1, b)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export statistics", "focusfortress_stats.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(load_stats(), indent=2), encoding="utf-8")
            info(self, f"Exported to {path}")
        except Exception as e:
            info(self, f"Export failed: {e}", title="Error")

    def _clear(self) -> None:
        if not confirm(self, "Delete all statistics? This cannot be undone."):
            return
        clear_stats()
        self._reload()
