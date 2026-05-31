"""Weekly click-and-drag schedule grid (7 days x 24 half-hour slots)."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ...engine import Engine
from ...models import ScheduleSlot
from ..common import confirm
from ..theme import Colors
from ..widgets import Card, PageHeader


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SLOTS_PER_DAY = 48   # 30-minute granularity


class ScheduleGrid(QWidget):
    changed = pyqtSignal()

    LEFT_PAD = 64
    TOP_PAD = 32
    CELL_GAP = 1
    CELL_RADIUS = 3

    def __init__(self) -> None:
        super().__init__()
        self.setMouseTracking(True)
        self._cells = [[False] * SLOTS_PER_DAY for _ in range(7)]
        self._dragging = False
        self._drag_value = True
        self.setMinimumHeight(380)
        self.setMinimumWidth(720)

    def sizeHint(self) -> QSize:
        return QSize(900, 420)

    def set_slots(self, slots: list[ScheduleSlot]) -> None:
        self._cells = [[False] * SLOTS_PER_DAY for _ in range(7)]
        for s in slots:
            try:
                sh, sm = [int(x) for x in s.start.split(":")]
                eh, em = [int(x) for x in s.end.split(":")]
            except Exception:
                continue
            start = (sh * 60 + sm) // 30
            end = (eh * 60 + em) // 30
            d = s.day
            if 0 <= d < 7:
                for i in range(start, min(end, SLOTS_PER_DAY)):
                    self._cells[d][i] = True
        self.update()

    def to_slots(self) -> list[ScheduleSlot]:
        out: list[ScheduleSlot] = []
        for d in range(7):
            i = 0
            while i < SLOTS_PER_DAY:
                if not self._cells[d][i]:
                    i += 1; continue
                j = i
                while j < SLOTS_PER_DAY and self._cells[d][j]:
                    j += 1
                sh, sm = divmod(i * 30, 60)
                eh, em = divmod(j * 30, 60)
                out.append(ScheduleSlot(
                    day=d,
                    start=f"{sh:02d}:{sm:02d}",
                    end=f"{eh:02d}:{em:02d}" if eh < 24 else "23:59",
                ))
                i = j
        return out

    # ----- interaction -----
    def _cell_at(self, x: int, y: int) -> Optional[tuple[int, int]]:
        lx = self.LEFT_PAD
        ty = self.TOP_PAD
        rw = self.width() - lx - 6
        rh = self.height() - ty - 6
        if rw <= 0 or rh <= 0 or x < lx or y < ty:
            return None
        col = int((x - lx) / rw * SLOTS_PER_DAY)
        row = int((y - ty) / rh * 7)
        if 0 <= col < SLOTS_PER_DAY and 0 <= row < 7:
            return row, col
        return None

    def mousePressEvent(self, e: QMouseEvent) -> None:
        cell = self._cell_at(int(e.position().x()), int(e.position().y()))
        if not cell:
            return
        r, c = cell
        self._dragging = True
        self._drag_value = not self._cells[r][c]
        self._cells[r][c] = self._drag_value
        self.update()
        self.changed.emit()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if not self._dragging:
            return
        cell = self._cell_at(int(e.position().x()), int(e.position().y()))
        if not cell:
            return
        r, c = cell
        if self._cells[r][c] != self._drag_value:
            self._cells[r][c] = self._drag_value
            self.update()
            self.changed.emit()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._dragging = False

    # ----- preset helpers -----
    def fill_range(self, days: list[int], start_min: int, end_min: int,
                   value: bool = True) -> None:
        """Paint ``value`` across ``days`` for the [start_min, end_min) window.

        Minutes are clock minutes from 00:00. A window where ``end_min`` <=
        ``start_min`` wraps past midnight (e.g. 22:00-06:00)."""
        for d in days:
            if not (0 <= d < 7):
                continue
            if end_min <= start_min:
                # Wrap midnight: [start, 24:00) then [00:00, end).
                self._paint_slots(d, start_min, 24 * 60, value)
                self._paint_slots(d, 0, end_min, value)
            else:
                self._paint_slots(d, start_min, end_min, value)
        self.update()
        self.changed.emit()

    def _paint_slots(self, day: int, start_min: int, end_min: int, value: bool) -> None:
        start = max(0, start_min // 30)
        end = min(SLOTS_PER_DAY, end_min // 30)
        for i in range(start, end):
            self._cells[day][i] = value

    def clear_day(self, day: int) -> None:
        if 0 <= day < 7:
            self._cells[day] = [False] * SLOTS_PER_DAY
            self.update()
            self.changed.emit()

    def clear_all(self) -> None:
        self._cells = [[False] * SLOTS_PER_DAY for _ in range(7)]
        self.update()
        self.changed.emit()

    def copy_day_to_all(self, src_day: int) -> None:
        if not (0 <= src_day < 7):
            return
        row = list(self._cells[src_day])
        for d in range(7):
            self._cells[d] = list(row)
        self.update()
        self.changed.emit()

    # ----- painting -----
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        lx = self.LEFT_PAD
        ty = self.TOP_PAD
        rw = self.width() - lx - 6
        rh = self.height() - ty - 6
        cw = rw / SLOTS_PER_DAY
        ch = rh / 7

        on = QColor(Colors.ACCENT)
        off = QColor(Colors.SURFACE_ALT)
        grid = QColor(Colors.BORDER)

        # Day background bands (subtle row highlight)
        for r in range(7):
            y = ty + r * ch
            p.fillRect(QRectF(lx - 4, y, rw + 8, ch),
                       QColor(Colors.SURFACE))

        # Cells
        p.setPen(Qt.PenStyle.NoPen)
        for r in range(7):
            for c in range(SLOTS_PER_DAY):
                x = lx + c * cw + self.CELL_GAP / 2
                y = ty + r * ch + self.CELL_GAP / 2
                rect = QRectF(x, y, cw - self.CELL_GAP, ch - self.CELL_GAP)
                p.setBrush(on if self._cells[r][c] else off)
                p.drawRoundedRect(rect, self.CELL_RADIUS, self.CELL_RADIUS)

        # Hour grid lines
        p.setPen(QPen(grid, 1))
        for c in range(0, SLOTS_PER_DAY + 1, 2):
            x = lx + c * cw
            if c == 0 or c == SLOTS_PER_DAY:
                p.setPen(QPen(QColor(Colors.BORDER), 1))
            else:
                p.setPen(QPen(grid, 1, Qt.PenStyle.DotLine))
            p.drawLine(int(x), ty - 4, int(x), ty + int(rh) + 2)

        # Row separators
        p.setPen(QPen(QColor(Colors.BORDER), 1))
        for r in range(8):
            y = ty + r * ch
            p.drawLine(lx - 4, int(y), lx + int(rw) + 4, int(y))

        # Day labels
        day_font = QFont(self.font())
        day_font.setPointSize(10)
        day_font.setBold(True)
        p.setFont(day_font)
        p.setPen(QColor(Colors.TEXT))
        for r, name in enumerate(DAYS_SHORT):
            y = ty + r * ch + ch / 2 + 4
            p.drawText(8, int(y), name)

        # Hour labels
        hour_font = QFont(self.font())
        hour_font.setPointSize(9)
        p.setFont(hour_font)
        p.setPen(QColor(Colors.TEXT_MUTED))
        for h in range(0, 25, 3):
            x = lx + (h * 2) * cw
            label = f"{h:02d}:00"
            p.drawText(int(x) - 16, ty - 10, label)


class ScheduleTab(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # Header with actions
        self.header = PageHeader(
            "Schedule",
            "Click and drag to mark blocked half-hour slots across the week."
        )
        self.combo = QComboBox()
        self.combo.setMinimumWidth(200)
        save_btn = QPushButton("Save schedule")
        save_btn.setProperty("variant", "primary")
        clear_btn = QPushButton("Clear week")
        clear_btn.setProperty("variant", "danger")

        self.header.add_action(self._labeled("Block", self.combo))
        self.header.add_action(clear_btn)
        self.header.add_action(save_btn)
        v.addWidget(self.header)

        # Grid card
        grid_card = Card(
            "Weekly grid",
            "Indigo cells = blocked. Drag to paint or erase.",
        )

        # Preset toolbar (report §2.8): quick fills for common patterns.
        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        preset_row.addWidget(self._preset_label("Presets"))
        weekdays_btn = QPushButton("Weekdays 9–5")
        nights_btn = QPushButton("Nights 22:00–06:00")
        self.copy_day_combo = QComboBox()
        for name in DAYS:
            self.copy_day_combo.addItem(name)
        copy_btn = QPushButton("Copy day → all")
        clear_day_btn = QPushButton("Clear day")
        clear_all_btn = QPushButton("Clear all")
        clear_all_btn.setProperty("variant", "danger")
        weekdays_btn.clicked.connect(self._preset_weekdays)
        nights_btn.clicked.connect(self._preset_nights)
        copy_btn.clicked.connect(self._copy_day_to_all)
        clear_day_btn.clicked.connect(self._clear_day)
        clear_all_btn.clicked.connect(self._clear_all)
        preset_row.addWidget(weekdays_btn)
        preset_row.addWidget(nights_btn)
        preset_row.addSpacing(12)
        preset_row.addWidget(self.copy_day_combo)
        preset_row.addWidget(copy_btn)
        preset_row.addWidget(clear_day_btn)
        preset_row.addStretch(1)
        preset_row.addWidget(clear_all_btn)
        grid_card.addLayout(preset_row)

        self.grid = ScheduleGrid()
        grid_card.addWidget(self.grid, 1)
        v.addWidget(grid_card, 1)

        self.combo.currentIndexChanged.connect(self._on_block_changed)
        save_btn.clicked.connect(self._save)
        clear_btn.clicked.connect(self._clear)
        self._reload()

    def _labeled(self, label: str, widget: QWidget) -> QWidget:
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(8)
        lbl = QLabel(label.upper())
        lbl.setStyleSheet(
            f"color:{Colors.TEXT_MUTED};font-size:10.5px;"
            f"font-weight:700;letter-spacing:1px;"
        )
        l.addWidget(lbl)
        l.addWidget(widget)
        return w

    def showEvent(self, e) -> None:
        self._reload()
        super().showEvent(e)

    def _reload(self) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        for b in self.engine.config.blocks:
            self.combo.addItem(b.name)
        self.combo.blockSignals(False)
        self._on_block_changed()

    def _current_block(self):
        idx = self.combo.currentIndex()
        if idx < 0 or idx >= len(self.engine.config.blocks):
            return None
        return self.engine.config.blocks[idx]

    def _on_block_changed(self) -> None:
        b = self._current_block()
        if not b:
            self.grid.set_slots([])
            return
        self.grid.set_slots(b.schedule)

    def _save(self) -> None:
        b = self._current_block()
        if not b:
            return
        b.schedule = self.grid.to_slots()
        self.engine.save()

    def _clear(self) -> None:
        self.grid.set_slots([])

    # ----- presets -----
    def _preset_label(self, text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(
            f"color:{Colors.TEXT_MUTED};font-size:10.5px;"
            f"font-weight:700;letter-spacing:1px;"
        )
        return lbl

    def _preset_weekdays(self) -> None:
        # Monday–Friday, 09:00–17:00.
        self.grid.fill_range([0, 1, 2, 3, 4], 9 * 60, 17 * 60, True)

    def _preset_nights(self) -> None:
        # Every day, 22:00–06:00 (wraps midnight).
        self.grid.fill_range(list(range(7)), 22 * 60, 6 * 60, True)

    def _copy_day_to_all(self) -> None:
        src = self.copy_day_combo.currentIndex()
        if src < 0:
            return
        if confirm(self, f"Copy {DAYS[src]}'s schedule to every day? "
                         "This overwrites the other days."):
            self.grid.copy_day_to_all(src)

    def _clear_day(self) -> None:
        src = self.copy_day_combo.currentIndex()
        if src >= 0:
            self.grid.clear_day(src)

    def _clear_all(self) -> None:
        if confirm(self, "Clear the entire week's schedule?"):
            self.grid.clear_all()
