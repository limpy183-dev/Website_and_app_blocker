"""Main window: sidebar navigation + stacked pages.

The classic tab-row is gone. Instead, we present a modern, spacious
sidebar (brand, nav, live status) and a QStackedWidget that swaps pages
on the right.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton,
    QStackedWidget, QStatusBar, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from ..engine import Engine
from .warning_popup import WarningManager
from .tabs.advanced_tab import AdvancedTab
from .tabs.block_page_tab import BlockPageTab
from .tabs.blocks_tab import BlocksTab
from .tabs.frozen_tab import FrozenTurkeyTab
from .tabs.pomodoro_tab import PomodoroTab
from .tabs.schedule_tab import ScheduleTab
from .tabs.stats_tab import StatsTab
from .theme import Colors
from .widgets import BrandLogo, HLine, NavButton, SectionLabel, StatusPill


def _make_tray_icon() -> QIcon:
    size = 64
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(Colors.ACCENT))
    p.setPen(Qt.PenStyle.NoPen)
    path = QPainterPath()
    path.moveTo(32, 4)
    path.lineTo(58, 16)
    path.lineTo(54, 48)
    path.lineTo(32, 60)
    path.lineTo(10, 48)
    path.lineTo(6, 16)
    path.closeSubpath()
    p.drawPath(path)
    p.setPen(QColor(255, 255, 255))
    font = p.font()
    font.setPixelSize(28)
    font.setBold(True)
    p.setFont(font)
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "F")
    p.end()
    return QIcon(px)


# ----- Pages metadata -----------------------------------------------------
# (icon_char, label, factory)
_NAV_ITEMS: list[tuple[str, str, str]] = [
    ("\u25A3",  "Blocks",         "blocks"),
    ("\u25A6",  "Schedule",       "schedule"),
    ("\u25D4",  "Pomodoro",       "pomodoro"),
    ("\u2744",  "Frozen Turkey",  "frozen"),
    ("\u25A7",  "Block Page",     "blockpage"),
    ("\u2699",  "Advanced",       "advanced"),
    ("\u25B3",  "Statistics",     "stats"),
]


class MainWindow(QMainWindow):
    # Bridges engine warning events (emitted from the engine's background
    # thread) onto the Qt main thread, where popups may be created safely.
    _warning_event = pyqtSignal(object)

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine
        self.setWindowTitle("FocusFortress")
        self.setWindowIcon(_make_tray_icon())
        self.setMinimumSize(1080, 720)

        # -------- Build UI skeleton --------
        central = QWidget()
        central.setObjectName("Root")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = self._build_sidebar()
        root.addWidget(sidebar)

        # Right-side content area
        content = QWidget()
        content.setStyleSheet(f"background-color: {Colors.BG};")
        c = QVBoxLayout(content)
        c.setContentsMargins(28, 24, 28, 16)
        c.setSpacing(16)

        self.stack = QStackedWidget()
        c.addWidget(self.stack, 1)
        root.addWidget(content, 1)

        self.setCentralWidget(central)

        # -------- Instantiate tab pages --------
        self.blocks_tab    = BlocksTab(engine)
        self.schedule_tab  = ScheduleTab(engine)
        self.pomo_tab      = PomodoroTab(engine)
        self.frozen_tab    = FrozenTurkeyTab(engine)
        self.blockpage_tab = BlockPageTab(engine)
        self.advanced_tab  = AdvancedTab(engine)
        self.stats_tab     = StatsTab(engine)

        self._pages_by_key = {
            "blocks":    self.blocks_tab,
            "schedule":  self.schedule_tab,
            "pomodoro":  self.pomo_tab,
            "frozen":    self.frozen_tab,
            "blockpage": self.blockpage_tab,
            "advanced":  self.advanced_tab,
            "stats":     self.stats_tab,
        }
        for _, _, key in _NAV_ITEMS:
            self.stack.addWidget(self._pages_by_key[key])

        # Hook up nav
        for i, btn in enumerate(self._nav_buttons):
            btn.clicked.connect(lambda _=False, idx=i: self._go(idx))
        self._go(0)

        # -------- Status bar --------
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            f"color:{Colors.TEXT_MUTED};padding:2px 12px;font-weight:500;"
        )
        sb.addPermanentWidget(self._status_label)
        self._refresh_status()

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start()

        self._setup_tray()
        self._setup_warnings()

    # -------------------------------------------------------------- warnings
    def _setup_warnings(self) -> None:
        """Show a popup (+ optional sound) when a block fires its warning.

        The engine emits data-only events from its worker thread; we hop onto
        the Qt main thread via a signal before building any widgets.
        """
        self._warning_manager = WarningManager(parent=self)
        self._warning_event.connect(self._on_warning_event)
        # Listener runs on the engine thread - just re-emit onto the GUI thread.
        self.engine.add_warning_listener(self._warning_event.emit)

    def _on_warning_event(self, event) -> None:
        try:
            self._warning_manager.show_event(event)
        except Exception:
            pass

    # --------------------------------------------------------------- sidebar
    def _build_sidebar(self) -> QWidget:
        sb = QFrame()
        sb.setObjectName("Sidebar")
        sb.setFixedWidth(232)
        v = QVBoxLayout(sb)
        v.setContentsMargins(18, 22, 18, 18)
        v.setSpacing(8)

        # Brand row
        brand_row = QHBoxLayout()
        brand_row.setSpacing(12)
        brand_row.addWidget(BrandLogo(36))
        brand_txt = QVBoxLayout()
        brand_txt.setSpacing(0)
        name = QLabel("FocusFortress")
        name.setObjectName("Brand")
        sub = QLabel("DISTRACTION-FREE")
        sub.setObjectName("BrandSub")
        brand_txt.addWidget(name)
        brand_txt.addWidget(sub)
        brand_row.addLayout(brand_txt)
        brand_row.addStretch(1)
        v.addLayout(brand_row)
        v.addSpacing(6)
        v.addWidget(HLine())
        v.addSpacing(6)

        # Nav buttons (split into focus vs system sections for style)
        self._nav_buttons: list[NavButton] = []
        self._nav_group = QButtonGroup(sb)
        self._nav_group.setExclusive(True)

        v.addWidget(SectionLabel("Focus"))
        for icon_char, label, key in _NAV_ITEMS[:4]:  # blocks/schedule/pomo/frozen
            btn = NavButton(icon_char, label)
            self._nav_group.addButton(btn)
            self._nav_buttons.append(btn)
            v.addWidget(btn)

        v.addSpacing(4)
        v.addWidget(SectionLabel("System"))
        for icon_char, label, key in _NAV_ITEMS[4:]:  # blockpage/advanced/stats
            btn = NavButton(icon_char, label)
            self._nav_group.addButton(btn)
            self._nav_buttons.append(btn)
            v.addWidget(btn)

        v.addStretch(1)

        # Live status block at bottom
        self._sidebar_pill = StatusPill("  INACTIVE  ", StatusPill.KIND_OFF)
        v.addWidget(self._sidebar_pill)

        self._sidebar_status = QLabel("0 / 0 blocks enabled")
        self._sidebar_status.setStyleSheet(
            f"color:{Colors.TEXT_MUTED}; font-size:11px; padding:6px 2px 0 2px;"
        )
        v.addWidget(self._sidebar_status)

        return sb

    # -------------------------------------------------------------- actions
    def _go(self, index: int) -> None:
        for i, b in enumerate(self._nav_buttons):
            b.setChecked(i == index)
        self.stack.setCurrentIndex(index)

    # ---------------------------------------------------------------- tray
    def _setup_tray(self) -> None:
        self._tray_icon = QSystemTrayIcon(_make_tray_icon(), self)
        self._tray_icon.setToolTip("FocusFortress")
        self._tray_menu = QMenu(self)
        self._tray_open_action = self._tray_menu.addAction("Open FocusFortress")
        self._tray_open_action.triggered.connect(self._show_from_tray)
        self._tray_icon.setContextMenu(self._tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        R = QSystemTrayIcon.ActivationReason
        if reason in (R.Trigger, R.DoubleClick, R.MiddleClick):
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        # Wait for the tray context menu to fully close before restoring.
        QTimer.singleShot(100, self._restore_window)

    def _restore_window(self) -> None:
        # Ensure the window is visible first.
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMinimized)
        self.show()
        self.showNormal()
        self.raise_()
        self.activateWindow()

        # On Windows, elevated processes are blocked from stealing focus by the
        # OS.  Use ctypes to call SetForegroundWindow directly which works
        # reliably even from an elevated context.
        try:
            import ctypes
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            # Allow ourselves to set the foreground window.
            user32.AllowSetForegroundWindow(ctypes.c_ulong(-1))  # ASFW_ANY
            # If the window is minimised, restore it first (SW_RESTORE = 9).
            user32.ShowWindow(hwnd, 9)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()

    def _refresh_status(self) -> None:
        active = sum(1 for b in self.engine.config.blocks if b.enabled)
        total = len(self.engine.config.blocks)
        self._status_label.setText(f"{active} of {total} blocks enabled")
        self._sidebar_status.setText(f"{active} / {total} blocks enabled")
        if active > 0:
            self._sidebar_pill.setText("  ACTIVE  ")
            self._sidebar_pill.set_kind(StatusPill.KIND_OK)
        else:
            self._sidebar_pill.setText("  IDLE  ")
            self._sidebar_pill.set_kind(StatusPill.KIND_OFF)
