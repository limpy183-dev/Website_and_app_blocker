"""Main window: sidebar navigation + stacked pages.

The classic tab-row is gone. Instead, we present a modern, spacious
sidebar (brand, nav, live status) and a QStackedWidget that swaps pages
on the right.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMenu, QMessageBox, QPushButton, QStackedWidget, QStatusBar,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .. import locks
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
    # Bridges a Frozen Turkey pre-action request (action, warn_seconds) from the
    # engine thread onto the GUI thread.
    _frozen_request = pyqtSignal(str, int)

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
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start()

        self._setup_tray()
        self._setup_warnings()
        self._setup_frozen_countdown()

    # ------------------------------------------------------- frozen countdown
    def _setup_frozen_countdown(self) -> None:
        """Show a cancellable countdown before a Frozen Turkey action."""
        self._frozen_dialog = None
        self._frozen_request.connect(self._on_frozen_request)
        # Engine calls this on its worker thread -> re-emit onto the GUI thread.
        try:
            self.engine.set_frozen_action_handler(
                lambda action, secs: self._frozen_request.emit(action, int(secs))
            )
        except Exception:
            pass

    def _on_frozen_request(self, action: str, seconds: int) -> None:
        from .frozen_warning_dialog import FrozenCountdownDialog
        # Only one countdown at a time.
        if self._frozen_dialog is not None:
            return

        def _fire(act: str) -> None:
            self._frozen_dialog = None
            try:
                self.engine.perform_frozen_action(act)
            except Exception:
                pass

        def _cancel() -> None:
            self._frozen_dialog = None
            try:
                self.engine.cancel_frozen_turkey()
            except Exception:
                pass

        try:
            dlg = FrozenCountdownDialog(action, seconds, _fire, _cancel, parent=self)
            self._frozen_dialog = dlg
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
        except Exception:
            # If the dialog can't be shown, fail safe: run the action so the
            # rule still has effect.
            self._frozen_dialog = None
            try:
                self.engine.perform_frozen_action(action)
            except Exception:
                pass

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
        self._tray_menu.addSeparator()
        # Per-block start/stop actions live in their own submenu, rebuilt each
        # time the menu is shown so it reflects the current state.
        self._tray_blocks_menu = self._tray_menu.addMenu("Blocks")
        self._tray_pause_action = self._tray_menu.addAction("Pause 5 min")
        self._tray_pause_action.triggered.connect(lambda: self._pause_all(5))
        self._tray_menu.addSeparator()
        self._tray_quit_action = self._tray_menu.addAction("Quit")
        self._tray_quit_action.triggered.connect(self._on_quit)
        self._tray_menu.aboutToShow.connect(self._rebuild_tray_blocks_menu)
        self._tray_icon.setContextMenu(self._tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()
        # Track blocks paused via the tray so we can re-enable them.
        self._paused_blocks: list[str] = []
        self._pause_timer: QTimer | None = None

    def _rebuild_tray_blocks_menu(self) -> None:
        """Populate the Blocks submenu with start/stop toggles per block."""
        menu = self._tray_blocks_menu
        menu.clear()
        blocks = list(self.engine.config.blocks)
        if not blocks:
            act = menu.addAction("No blocks configured")
            act.setEnabled(False)
            return
        for b in blocks:
            label = f"{'Stop' if b.enabled else 'Start'} — {b.name}"
            act = menu.addAction(label)
            act.triggered.connect(lambda _=False, name=b.name: self._tray_toggle_block(name))

    def _tray_toggle_block(self, name: str) -> None:
        from ..engine import LockedError
        try:
            self.engine.toggle_block(name)
        except LockedError as e:
            self._tray_icon.showMessage(
                "Can't change block", e.reason,
                QSystemTrayIcon.MessageIcon.Warning, 4000,
            )
        self._refresh_status()

    def _pause_all(self, minutes: int) -> None:
        """Temporarily disable all currently-enabled (unlocked) blocks."""
        from ..engine import LockedError
        paused: list[str] = []
        for b in list(self.engine.config.blocks):
            if not b.enabled:
                continue
            try:
                if self.engine.set_block_enabled(b.name, False):
                    paused.append(b.name)
            except LockedError:
                # Locked blocks can't be paused - leave them on.
                pass
        if not paused:
            self._tray_icon.showMessage(
                "Nothing to pause",
                "No unlocked blocks are currently active.",
                QSystemTrayIcon.MessageIcon.Information, 3000,
            )
            return
        self._paused_blocks = paused
        if self._pause_timer is not None:
            self._pause_timer.stop()
        self._pause_timer = QTimer(self)
        self._pause_timer.setSingleShot(True)
        self._pause_timer.timeout.connect(self._resume_paused)
        self._pause_timer.start(minutes * 60 * 1000)
        self._tray_icon.showMessage(
            "Paused",
            f"Paused {len(paused)} block(s) for {minutes} min.",
            QSystemTrayIcon.MessageIcon.Information, 3000,
        )
        self._refresh_status()

    def _resume_paused(self) -> None:
        for name in self._paused_blocks:
            try:
                self.engine.set_block_enabled(name, True)
            except Exception:
                pass
        self._paused_blocks = []
        self._refresh_status()

    def _quit_blockers(self) -> list[str]:
        """Return human-readable reasons quitting is currently forbidden.

        An empty list means quitting is allowed. We refuse to quit while a
        block is *effectively active* (manually enabled or inside a schedule
        slot) and its lock would forbid disabling it right now -- otherwise
        quitting would be a trivial bypass of a locked block. Blocks that are
        not active never block quitting.
        """
        reasons: list[str] = []
        try:
            now = self.engine._now()
        except Exception:
            now = None
        try:
            blocks = list(self.engine.config.blocks)
        except Exception:
            return reasons
        for b in blocks:
            try:
                if now is not None:
                    active = self.engine._effective_enabled(b, now)
                else:
                    active = bool(getattr(b, "enabled", False))
            except Exception:
                active = bool(getattr(b, "enabled", False))
            if not active:
                continue
            try:
                allowed, reason = locks.can_disable(b)
            except Exception:
                # If we can't evaluate the lock, fail safe by refusing to quit
                # an active block.
                allowed, reason = False, "This block is locked."
            if not allowed:
                reasons.append(f"{getattr(b, 'name', 'A block')}: {reason}")
        return reasons

    def _on_quit(self) -> None:
        reasons = self._quit_blockers()
        if reasons:
            QMessageBox.warning(
                self,
                "Can't quit FocusFortress",
                "FocusFortress can't quit while a locked block is active:\n\n"
                + "\n".join(reasons),
            )
            return
        # Tear down enforcement, then quit the application.
        try:
            self.engine.shutdown()
        except Exception:
            pass
        app = QApplication.instance()
        if app is not None:
            app.quit()

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

    @staticmethod
    def _fmt_mmss(seconds: int) -> str:
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        return f"{m:02d}:{s:02d}"

    def _pomodoro_badge(self) -> str:
        """Return a short ' — Work 12:34' badge, or '' when no Pomodoro runs."""
        try:
            status = self.engine.pomodoro_status()
        except Exception:
            status = None
        if not status:
            return ""
        phase = {
            "work": "Work", "break": "Break", "long_break": "Long break",
        }.get(status["phase"], status["phase"].title())
        clock = self._fmt_mmss(status["remaining_seconds"])
        paused = " (paused)" if status.get("paused") else ""
        return f" — {phase} {clock}{paused}"

    def _refresh_status(self) -> None:
        active_blocks = [b for b in self.engine.config.blocks if b.enabled]
        active = len(active_blocks)
        total = len(self.engine.config.blocks)
        self._status_label.setText(f"{active} of {total} blocks enabled")
        self._sidebar_status.setText(f"{active} / {total} blocks enabled")
        if active > 0:
            self._sidebar_pill.setText("  ACTIVE  ")
            self._sidebar_pill.set_kind(StatusPill.KIND_OK)
        else:
            self._sidebar_pill.setText("  IDLE  ")
            self._sidebar_pill.set_kind(StatusPill.KIND_OFF)

        # Window title carries the live Pomodoro badge.
        self.setWindowTitle("FocusFortress" + self._pomodoro_badge())

        # Tray tooltip: active block list + Pomodoro phase.
        if active_blocks:
            names = ", ".join(b.name for b in active_blocks[:5])
            if active > 5:
                names += f", +{active - 5} more"
            tip = f"FocusFortress — {active} block(s) active: {names}"
        else:
            tip = "FocusFortress — idle"
        badge = self._pomodoro_badge()
        if badge:
            tip += f"\n{badge.lstrip(' — ')}"
        try:
            self._tray_icon.setToolTip(tip)
        except Exception:
            pass
