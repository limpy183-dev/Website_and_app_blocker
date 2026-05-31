"""Reusable custom widgets for the modern UI.

Kept framework-only (no business logic) so they can be shared freely
between tabs/pages.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt, QSize, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .theme import Colors


# ---------------------------------------------------------------------------
# Drop shadow helper
# ---------------------------------------------------------------------------

def add_shadow(widget: QWidget, blur: int = 24, dy: int = 6, alpha: int = 70) -> None:
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

class Card(QFrame):
    """Rounded panel with optional title/subtitle header."""

    def __init__(
        self,
        title: str | None = None,
        subtitle: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(18, 16, 18, 16)
        self._outer.setSpacing(12)

        if title or subtitle:
            head = QVBoxLayout()
            head.setSpacing(2)
            if title:
                lt = QLabel(title)
                lt.setObjectName("CardTitle")
                head.addWidget(lt)
            if subtitle:
                ls = QLabel(subtitle)
                ls.setObjectName("CardSubtitle")
                ls.setWordWrap(True)
                head.addWidget(ls)
            self._outer.addLayout(head)

        self._body = QVBoxLayout()
        self._body.setSpacing(10)
        self._body.setContentsMargins(0, 0, 0, 0)
        self._outer.addLayout(self._body, 1)

        add_shadow(self, blur=30, dy=8, alpha=55)

    def body(self) -> QVBoxLayout:
        return self._body

    def addWidget(self, w: QWidget, *a, **kw) -> None:  # type: ignore[override]
        self._body.addWidget(w, *a, **kw)

    def addLayout(self, l, *a, **kw) -> None:
        self._body.addLayout(l, *a, **kw)


# ---------------------------------------------------------------------------
# Stat card - big number + tiny label
# ---------------------------------------------------------------------------

class StatCard(Card):
    def __init__(self, label: str, value: str = "-", accent: str | None = None, parent=None) -> None:
        super().__init__(parent=parent)
        self._outer.setContentsMargins(18, 16, 18, 16)
        lab = QLabel(label.upper())
        lab.setObjectName("StatLabel")
        self._value_lbl = QLabel(value)
        self._value_lbl.setObjectName("StatNumber")
        if accent:
            self._value_lbl.setStyleSheet(f"color:{accent};")
        self._body.addWidget(lab)
        self._body.addWidget(self._value_lbl)
        self.setMinimumHeight(100)

    def set_value(self, value: str) -> None:
        self._value_lbl.setText(value)


# ---------------------------------------------------------------------------
# Page Header (title + subtitle + right-aligned actions)
# ---------------------------------------------------------------------------

class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None) -> None:
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        txt = QVBoxLayout()
        txt.setSpacing(2)
        self._title = QLabel(title)
        self._title.setObjectName("PageTitle")
        txt.addWidget(self._title)
        self._sub = QLabel(subtitle)
        self._sub.setObjectName("PageSubtitle")
        self._sub.setWordWrap(True)
        if subtitle:
            txt.addWidget(self._sub)
        h.addLayout(txt, 1)

        self._actions = QHBoxLayout()
        self._actions.setSpacing(8)
        h.addLayout(self._actions)

    def add_action(self, w: QWidget) -> None:
        self._actions.addWidget(w)

    def set_subtitle(self, text: str) -> None:
        self._sub.setText(text)


# ---------------------------------------------------------------------------
# Sidebar navigation button
# ---------------------------------------------------------------------------

class NavButton(QPushButton):
    def __init__(self, icon_char: str, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setText(f"  {icon_char}   {text}")
        f = self.font()
        f.setPointSizeF(f.pointSizeF())
        self.setFont(f)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


# ---------------------------------------------------------------------------
# Status pill
# ---------------------------------------------------------------------------

class StatusPill(QLabel):
    KIND_OK = "ok"
    KIND_OFF = "off"
    KIND_WARN = "warn"

    def __init__(self, text: str = "", kind: str = "off", parent=None) -> None:
        super().__init__(text, parent)
        self.set_kind(kind)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        if kind == self.KIND_OK:
            self.setObjectName("StatusPillOk")
        elif kind == self.KIND_WARN:
            self.setObjectName("StatusPillWarn")
        else:
            self.setObjectName("StatusPillOff")
        # Force re-apply
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


# ---------------------------------------------------------------------------
# Brand logo (crest) painted on the sidebar
# ---------------------------------------------------------------------------

class BrandLogo(QLabel):
    def __init__(self, size: int = 36, parent=None) -> None:
        super().__init__(parent)
        px = QPixmap(size * 2, size * 2)
        px.setDevicePixelRatio(2.0)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Shield
        s = size
        path = QPainterPath()
        path.moveTo(s / 2, 3)
        path.lineTo(s - 4, 9)
        path.lineTo(s - 6, s - 10)
        path.lineTo(s / 2, s - 3)
        path.lineTo(6, s - 10)
        path.lineTo(4, 9)
        path.closeSubpath()

        # Gradient-ish fill (two tones)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(Colors.ACCENT))
        p.drawPath(path)
        p.setBrush(QColor(Colors.ACCENT_HOV))
        small = QPainterPath()
        small.moveTo(s / 2, 6)
        small.lineTo(s - 7, 11)
        small.lineTo(s / 2, s / 2 + 2)
        small.closeSubpath()
        p.drawPath(small)

        # "F" mark
        p.setPen(QPen(QColor("white")))
        f = p.font()
        f.setPixelSize(int(s * 0.55))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRect(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "F")
        p.end()
        self.setPixmap(px)
        self.setFixedSize(size, size)


# ---------------------------------------------------------------------------
# Nice wrapping scroll area (for long pages)
# ---------------------------------------------------------------------------

class PageScroll(QScrollArea):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { background: transparent; }"
                           "QScrollArea > QWidget > QWidget { background: transparent; }")


# ---------------------------------------------------------------------------
# Section divider with small label
# ---------------------------------------------------------------------------

class SectionLabel(QLabel):
    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text.upper(), parent)
        self.setObjectName("NavSection")


# ---------------------------------------------------------------------------
# Combo box keyed by item data (not visible text)
# ---------------------------------------------------------------------------

class DataComboBox(QComboBox):
    """QComboBox whose selection is addressed by item *data* rather than text.

    ``addOption("Auto-close", "auto_close")`` then ``setCurrentData("auto_close")``
    selects it; ``currentData()`` returns the stored value.
    """

    def addOption(self, label: str, data) -> None:
        self.addItem(label, data)

    def setCurrentData(self, data) -> None:
        idx = self.findData(data)
        if idx >= 0:
            self.setCurrentIndex(idx)


# ---------------------------------------------------------------------------
# Horizontal separator line
# ---------------------------------------------------------------------------

class HLine(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background-color: {Colors.BORDER}; border: none;")
