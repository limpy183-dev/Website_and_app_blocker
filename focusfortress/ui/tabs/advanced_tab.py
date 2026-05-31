"""Advanced settings tab.

Two protections wrap this page:

* **Force Protect FocusFortress from Termination** - the strongest
  available kill-protection mode (DACL + console handler + priority +
  paired watchdogs).  Lives as a toggle inside the Anti-bypass card.

* **Advanced Settings Cooldown Lock** - any attempt to interact with a
  control on this page triggers a 1-hour cooldown.  Once the timer
  reaches zero the user gets a single editing session; saving re-arms
  the lock so the next change attempt requires another full hour wait.
"""
from __future__ import annotations

from typing import List

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QFormLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ... import cooldown
from ...engine import Engine
from ..common import info
from ..cooldown_dialog import CooldownDialog
from ..theme import Colors
from ..widgets import Card, PageHeader, PageScroll, StatusPill


# Events we treat as "user is trying to change a setting".
_GUARDED_EVENTS = {
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonDblClick,
    QEvent.Type.KeyPress,
    QEvent.Type.Wheel,
}


class AdvancedTab(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        self.header = PageHeader(
            "Advanced",
            "Fine-tune OS-level enforcement and anti-bypass safeguards."
        )
        self._lock_pill = StatusPill("  LOCKED  ", StatusPill.KIND_WARN)
        self.header.add_action(self._lock_pill)
        self._save_btn = QPushButton("Save settings")
        self._save_btn.setProperty("variant", "primary")
        self._save_btn.clicked.connect(self._on_save_clicked)
        self.header.add_action(self._save_btn)
        outer.addWidget(self.header)

        # Lock-status banner (visible while the cooldown is locked).
        self._banner = QLabel()
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(
            f"background:{Colors.WARNING_SOFT};"
            f"color:{Colors.WARNING};"
            f"border:1px solid {Colors.WARNING};"
            f"border-radius:10px;"
            f"padding:10px 14px;"
            f"font-weight:600;"
        )
        outer.addWidget(self._banner)

        # Scrolling content
        scroll = PageScroll()
        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(14)

        # OS-level enforcement
        core = Card(
            "OS-level enforcement",
            "Core protections applied while a block is active.",
        )
        self.cb_time = QCheckBox("Block system time changes")
        self.cb_tm = QCheckBox("Block Task Manager")
        self.cb_embed = QCheckBox("Block embedded (iframe) content")
        self.cb_start = QCheckBox("Start FocusFortress automatically with Windows")
        core.addWidget(self.cb_time)
        core.addWidget(self.cb_tm)
        core.addWidget(self.cb_embed)
        core.addWidget(self.cb_start)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Local proxy port:"))
        self.port = QSpinBox(); self.port.setRange(1024, 65535)
        self.port.setMaximumWidth(120)
        port_row.addWidget(self.port)
        port_row.addStretch(1)
        core.addLayout(port_row)
        v.addWidget(core)

        # Anti-bypass
        anti = Card(
            "Anti-bypass",
            "All toggles below are opt-in. Enable what you need.",
        )

        self.cb_force_protect = QCheckBox(
            "Force Protect FocusFortress from Termination"
        )
        f = self.cb_force_protect.font(); f.setBold(True)
        self.cb_force_protect.setFont(f)
        self.cb_force_protect.setStyleSheet(f"color:{Colors.TEXT};")
        self.cb_force_protect.setToolTip(
            "Strongest kill-protection mode.  Stacks: deny PROCESS_TERMINATE "
            "ACL on this process, swallow console signals, raise priority to "
            "HIGH, and run a pair of partner watchdogs that watch each other "
            "and instantly relaunch FocusFortress if it is somehow killed.  "
            "Active unconditionally while enabled - blocks do not need to be "
            "running."
        )
        force_blurb = QLabel(
            "Recommended.  Combines every available defence so Task Manager, "
            "taskkill, scripts, and signal-based exits cannot end the app, "
            "and instantly relaunches it if it ever does."
        )
        force_blurb.setWordWrap(True)
        force_blurb.setStyleSheet(
            f"color:{Colors.TEXT_MUTED}; font-size:11.5px; padding-left:26px;"
        )
        anti.addWidget(self.cb_force_protect)
        anti.addWidget(force_blurb)

        self.cb_protect = QCheckBox(
            "Protect FocusFortress from being terminated (Task Manager / taskkill)"
        )
        self.cb_protect.setToolTip(
            "Applies a deny-PROCESS_TERMINATE ACL to our own process while running."
        )

        self.cb_ignore_time = QCheckBox(
            "Ignore system time changes (use a monotonic clock)"
        )
        self.cb_ignore_time.setToolTip(
            "If you change the Windows clock, timer locks and schedule windows "
            "behave exactly as if you hadn't."
        )

        self.cb_watchdog = QCheckBox(
            "Run a watchdog that relaunches FocusFortress if it's killed"
        )
        self.cb_watchdog.setToolTip(
            "A tiny sidecar process polls our PID. If the main app disappears "
            "while a block is active, it is restarted automatically."
        )

        self.cb_revert_proxy = QCheckBox(
            "Revert WinINET proxy tampering while a block is active"
        )
        self.cb_doh = QCheckBox(
            "Block public DNS-over-HTTPS endpoints (Cloudflare, Google, Quad9...)"
        )
        self.cb_doh.setToolTip(
            "Stops Chrome/Edge/Firefox's built-in DoH from bypassing the hosts "
            "file. List your own DoH host below to keep it working."
        )

        anti.addWidget(self.cb_protect)
        anti.addWidget(self.cb_ignore_time)
        anti.addWidget(self.cb_watchdog)
        anti.addWidget(self.cb_revert_proxy)
        anti.addWidget(self.cb_doh)

        lbl = QLabel("DOH ALLOWLIST")
        lbl.setStyleSheet(
            f"color:{Colors.TEXT_MUTED};font-size:10.5px;"
            f"font-weight:700;letter-spacing:1px;padding-top:4px;"
        )
        anti.addWidget(lbl)

        self.doh_allow = QPlainTextEdit()
        self.doh_allow.setPlaceholderText(
            "One DoH host (or substring) per line that should NOT be blocked.\n"
            "Example:\n    nextdns.io\n    my-corp-dns.example.com"
        )
        self.doh_allow.setFixedHeight(90)
        anti.addWidget(self.doh_allow)
        v.addWidget(anti)

        # CLI reference card (read-only, never gated).
        cli_card = Card(
            "Command line",
            "Control FocusFortress without opening the window.",
        )
        cli = QLabel(
            "python -m focusfortress cli start|stop|toggle <name>\n"
            "python -m focusfortress cli lock <name> --timer 02:00\n"
            "python -m focusfortress cli lock <name> --random 64\n"
            "python -m focusfortress cli lock <name> --restart\n"
            "python -m focusfortress cli lock <name> --password MYPW\n"
            "python -m focusfortress cli list"
        )
        cli.setStyleSheet(
            f"color:{Colors.TEXT};font-family:'Cascadia Mono',Consolas,monospace;"
            f"font-size:12px;background:{Colors.BG};padding:12px;border-radius:8px;"
            f"border:1px solid {Colors.BORDER};"
        )
        cli_card.addWidget(cli)
        v.addWidget(cli_card)

        v.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self._load()

        # Build the list of every input that must be cooldown-gated.
        self._guarded: List[QWidget] = [
            self.cb_time, self.cb_tm, self.cb_embed, self.cb_start, self.port,
            self.cb_force_protect, self.cb_protect, self.cb_ignore_time,
            self.cb_watchdog, self.cb_revert_proxy, self.cb_doh, self.doh_allow,
        ]
        for w in self._guarded:
            w.installEventFilter(self)
            # Spinboxes have an internal QLineEdit child; install on it too
            # so typed-character attempts also trigger the cooldown.
            if isinstance(w, QAbstractSpinBox):
                le = w.lineEdit()
                if le is not None:
                    le.installEventFilter(self)

        # Live banner refresh.
        self._banner_timer = QTimer(self)
        self._banner_timer.setInterval(1000)
        self._banner_timer.timeout.connect(self._refresh_banner)
        self._banner_timer.start()
        self._refresh_banner()

        # Stash original values so we can revert any mid-session edits if
        # the user closes/cancels without unlocking.  Re-snapshotted on
        # successful save.
        self._snapshot = self._snapshot_values()

    # ------------------------------------------------------------------
    # event filter - core of the cooldown lock
    # ------------------------------------------------------------------

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() in _GUARDED_EVENTS and self._is_locked():
            # Show / refresh the cooldown modal.  The very first attempt
            # also kicks off the persistent 1-hour timer.
            self._handle_blocked_attempt()
            return True  # consume - controls do NOT see this event
        return super().eventFilter(obj, event)

    def _is_locked(self) -> bool:
        return not cooldown.is_unlocked()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        """Consume an unused unlock when the tab leaves the screen.

        ``cooldown.mark_unlocked()`` persists ``unlocked:true`` as soon as the
        1-hour wait elapses and the user clicks Unlock.  The normal Save flow
        consumes it (``_save`` -> ``cooldown.consume_unlock()``), re-arming the
        lock.  But if the user unlocks and then navigates away / closes the
        window WITHOUT saving, that flag would survive and grant a free edit in
        the next session.

        This page is a child of a ``QStackedWidget`` and the main window's
        ``closeEvent`` calls ``self.hide()``, so a hideEvent fires both when the
        user switches tabs and when the window is hidden/closed.  If an unlock
        is still outstanding (i.e. it was NOT consumed by a save) we consume it
        here so an unused unlock never persists.  After a save the state no
        longer reports unlocked, so this never double-consumes.
        """
        try:
            if cooldown.is_unlocked():
                cooldown.consume_unlock()
                self._refresh_banner()
        except Exception:
            pass
        super().hideEvent(event)

    def _handle_blocked_attempt(self) -> None:
        # Ensure a timer is running.  start_cooldown() is idempotent: if
        # one is already counting down it preserves the existing deadline.
        if not cooldown.is_running() and not cooldown.is_unlocked():
            cooldown.start_cooldown()
        self._refresh_banner()
        # Modal blocks until the user closes or unlocks.
        dlg = CooldownDialog(self)
        result = dlg.exec()
        # If the dialog was accepted (timer hit 0 + user clicked Unlock),
        # cooldown.is_unlocked() is now True.  Refresh UI accordingly.
        if cooldown.is_unlocked():
            self._refresh_banner()
            info(self,
                 "Advanced settings unlocked. Make your changes, then click "
                 "Save settings. The 1-hour wait will restart on save.")
        else:
            self._refresh_banner()

    # ------------------------------------------------------------------
    # banner / lock UI
    # ------------------------------------------------------------------

    def _refresh_banner(self) -> None:
        if cooldown.is_unlocked():
            self._banner.setText(
                "Unlocked. You can now make changes. Saving will re-arm the "
                "1-hour cooldown."
            )
            self._banner.setStyleSheet(
                f"background:{Colors.SUCCESS_SOFT};"
                f"color:{Colors.SUCCESS};"
                f"border:1px solid {Colors.SUCCESS};"
                f"border-radius:10px;padding:10px 14px;font-weight:600;"
            )
            self._lock_pill.setText("  UNLOCKED  ")
            self._lock_pill.set_kind(StatusPill.KIND_OK)
            self._save_btn.setEnabled(True)
        elif cooldown.is_running():
            rem = cooldown.format_remaining(cooldown.remaining_seconds())
            self._banner.setText(
                f"Advanced settings are locked.  Cooldown: {rem} remaining.  "
                f"Click any control to view the timer.  Settings cannot be "
                f"saved until the timer ends."
            )
            self._banner.setStyleSheet(
                f"background:{Colors.WARNING_SOFT};"
                f"color:{Colors.WARNING};"
                f"border:1px solid {Colors.WARNING};"
                f"border-radius:10px;padding:10px 14px;font-weight:600;"
            )
            self._lock_pill.setText(f"  {rem}  ")
            self._lock_pill.set_kind(StatusPill.KIND_WARN)
            self._save_btn.setEnabled(False)
        else:
            self._banner.setText(
                "Advanced settings are locked.  Any change attempt starts a "
                "1-hour cooldown that must elapse before edits are accepted."
            )
            self._banner.setStyleSheet(
                f"background:{Colors.SURFACE_ALT};"
                f"color:{Colors.TEXT_MUTED};"
                f"border:1px solid {Colors.BORDER};"
                f"border-radius:10px;padding:10px 14px;font-weight:600;"
            )
            self._lock_pill.setText("  LOCKED  ")
            self._lock_pill.set_kind(StatusPill.KIND_OFF)
            self._save_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def _snapshot_values(self) -> dict:
        s = self.engine.config.settings
        return {
            "block_time_changes": s.block_time_changes,
            "block_task_manager": s.block_task_manager,
            "start_with_windows": s.start_with_windows,
            "proxy_port": s.proxy_port,
            "block_embedded": all(b.block_embedded for b in self.engine.config.blocks)
                              if self.engine.config.blocks else True,
            "force_protect_termination": s.force_protect_termination,
            "protect_process": s.protect_process,
            "ignore_time_changes": s.ignore_time_changes,
            "watchdog_enabled": s.watchdog_enabled,
            "revert_proxy_tampering": s.revert_proxy_tampering,
            "block_doh": s.block_doh,
            "doh_allowlist": list(s.doh_allowlist),
        }

    def _load(self) -> None:
        s = self.engine.config.settings
        self.cb_time.setChecked(s.block_time_changes)
        self.cb_tm.setChecked(s.block_task_manager)
        self.cb_start.setChecked(s.start_with_windows)
        self.port.setValue(s.proxy_port)
        self.cb_embed.setChecked(
            all(b.block_embedded for b in self.engine.config.blocks)
        ) if self.engine.config.blocks else self.cb_embed.setChecked(True)

        self.cb_force_protect.setChecked(s.force_protect_termination)
        self.cb_protect.setChecked(s.protect_process)
        self.cb_ignore_time.setChecked(s.ignore_time_changes)
        self.cb_watchdog.setChecked(s.watchdog_enabled)
        self.cb_revert_proxy.setChecked(s.revert_proxy_tampering)
        self.cb_doh.setChecked(s.block_doh)
        self.doh_allow.setPlainText("\n".join(s.doh_allowlist))

    def _on_save_clicked(self) -> None:
        # Defence in depth - even if the event filter were bypassed, a
        # locked Save is refused here.
        if not cooldown.is_unlocked():
            self._handle_blocked_attempt()
            return
        self._save()

    def _save(self) -> None:
        s = self.engine.config.settings
        s.block_time_changes = self.cb_time.isChecked()
        s.block_task_manager = self.cb_tm.isChecked()
        s.start_with_windows = self.cb_start.isChecked()
        s.proxy_port = self.port.value()
        for b in self.engine.config.blocks:
            b.block_embedded = self.cb_embed.isChecked()

        s.force_protect_termination = self.cb_force_protect.isChecked()
        s.protect_process = self.cb_protect.isChecked()
        s.ignore_time_changes = self.cb_ignore_time.isChecked()
        s.watchdog_enabled = self.cb_watchdog.isChecked()
        s.revert_proxy_tampering = self.cb_revert_proxy.isChecked()
        s.block_doh = self.cb_doh.isChecked()
        s.doh_allowlist = [
            l.strip() for l in self.doh_allow.toPlainText().splitlines() if l.strip()
        ]

        self.engine.save()

        # Apply live so the user sees immediate effect.
        try:
            from ... import clock
            clock.configure(s.ignore_time_changes)
            if s.ignore_time_changes:
                clock.reanchor()
            self.engine._apply()
        except Exception:
            pass

        from ...autostart import set_autostart, is_autostart_enabled
        msg_extra = ""
        try:
            set_autostart(s.start_with_windows)
            if s.start_with_windows:
                if is_autostart_enabled():
                    msg_extra = " Startup enabled."
                else:
                    msg_extra = " Startup registration could not be verified."
            else:
                msg_extra = " Startup disabled."
        except Exception as e:
            msg_extra = f" Startup update failed: {e}"

        # Re-arm the cooldown lock - per spec, the next change attempt
        # must wait another full hour.
        cooldown.consume_unlock()
        self._snapshot = self._snapshot_values()
        self._refresh_banner()
        info(self, f"Advanced settings saved.{msg_extra}\n\n"
                   f"The 1-hour cooldown lock has been re-armed.")
