"""Blocks tab: create/edit/enable block lists with websites, apps and locks."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTime
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QSlider, QSpinBox, QSplitter,
    QTabWidget, QTimeEdit, QVBoxLayout, QWidget,
)

from dataclasses import asdict

from ...config_store import DEFAULT_DISTRACTIONS
from ...engine import Engine
from ...locks import can_disable, describe_lock
from ...models import BlockList, LockConfig, WarningConfig, _only_known
from ...security import hash_password, random_unlock_text
from ...sounds import builtin_sound_names, ensure_builtin_sounds
from ...warnings import WARNING_PRESETS, apply_warning_preset, resolve_warning_message
from ..common import confirm, error, info
from ..theme import Colors
from ..widgets import Card, DataComboBox, PageHeader, StatusPill


# ---------------------------------------------------------------------------
# Lock editor dialog
# ---------------------------------------------------------------------------
class _LockEditor(QDialog):
    """Configure a lock for a block."""
    def __init__(self, parent, lock: LockConfig):
        super().__init__(parent)
        self.setWindowTitle("Configure lock")
        self.setMinimumWidth(460)
        self.lock = LockConfig(**lock.__dict__)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(14)

        title = QLabel("Lock method")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        v.addWidget(title)

        self.kind = QComboBox()
        self.kind.addItems(["none", "timer", "random", "range", "restart", "password"])
        self.kind.setCurrentText(self.lock.kind or "none")
        v.addWidget(self.kind)

        desc = QLabel(
            "timer: unlock after a delay   random: type a long string   "
            "range: allowed/blocked hours   restart: reboot to unlock   "
            "password: secret unlock"
        )
        desc.setStyleSheet(f"color:{Colors.TEXT_MUTED};font-size:11px;")
        desc.setWordWrap(True)
        v.addWidget(desc)

        # Timer
        self.timer_hours = QSpinBox(); self.timer_hours.setRange(0, 720); self.timer_hours.setValue(2)
        self.timer_minutes = QSpinBox(); self.timer_minutes.setRange(0, 59)
        timer_row = QHBoxLayout()
        timer_row.addWidget(QLabel("From now:"))
        timer_row.addWidget(self.timer_hours); timer_row.addWidget(QLabel("h"))
        timer_row.addWidget(self.timer_minutes); timer_row.addWidget(QLabel("m"))
        timer_row.addStretch(1)
        timer_w = QWidget(); timer_w.setLayout(timer_row)

        # Random
        self.random_len = QSpinBox(); self.random_len.setRange(1, 999); self.random_len.setValue(self.lock.random_length)
        random_row = QHBoxLayout()
        random_row.addWidget(QLabel("Length (1-999):"))
        random_row.addWidget(self.random_len)
        random_row.addStretch(1)
        random_w = QWidget(); random_w.setLayout(random_row)

        # Range
        self.range_start = QTimeEdit(QTime.fromString(self.lock.range_start, "HH:mm"))
        self.range_end = QTimeEdit(QTime.fromString(self.lock.range_end, "HH:mm"))
        self.range_mode = QComboBox(); self.range_mode.addItems(["block_during", "allow_during"])
        self.range_mode.setCurrentText(self.lock.range_mode)
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Start")); range_row.addWidget(self.range_start)
        range_row.addWidget(QLabel("End")); range_row.addWidget(self.range_end)
        range_row.addWidget(self.range_mode)
        range_w = QWidget(); range_w.setLayout(range_row)

        # Password
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("New password (leave empty to keep existing)")

        def section(label_text: str, widget: QWidget) -> None:
            lbl = QLabel(label_text)
            lbl.setStyleSheet(
                f"color:{Colors.TEXT_MUTED};font-size:10.5px;"
                f"font-weight:700;letter-spacing:1.2px;"
            )
            v.addWidget(lbl)
            v.addWidget(widget)

        section("TIMER",    timer_w)
        section("RANDOM",   random_w)
        section("RANGE",    range_w)
        section("PASSWORD", self.password)

        hint = QLabel("Restart lock has no options (reboot to unlock).")
        hint.setStyleSheet(f"color:{Colors.TEXT_FAINT};font-size:11px;font-style:italic;")
        v.addWidget(hint)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_btn = bb.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setProperty("variant", "primary")
        bb.accepted.connect(self._accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _accept(self) -> None:
        self.lock.kind = self.kind.currentText()
        self.lock.random_length = self.random_len.value()
        self.lock.range_start = self.range_start.time().toString("HH:mm")
        self.lock.range_end = self.range_end.time().toString("HH:mm")
        self.lock.range_mode = self.range_mode.currentText()
        if self.lock.kind == "timer":
            until = dt.datetime.now() + dt.timedelta(
                hours=self.timer_hours.value(), minutes=self.timer_minutes.value()
            )
            self.lock.until = until.isoformat(timespec="minutes")
        if self.lock.kind == "password" and self.password.text():
            h, s = hash_password(self.password.text())
            self.lock.password_hash, self.lock.password_salt = h, s
        self.accept()


# ---------------------------------------------------------------------------
# Main tab
# ---------------------------------------------------------------------------
class BlocksTab(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine
        self._current: Optional[BlockList] = None
        self._warning_manager = None  # lazily created on first Test warning

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        # Header
        self.header = PageHeader(
            "Blocks",
            "Create and manage block lists. Each one can target websites, "
            "executables, window titles and Store apps."
        )
        self.new_btn = QPushButton("+ New block")
        self.new_btn.setProperty("variant", "primary")
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.clicked.connect(self._new_block)
        self.header.add_action(self.new_btn)
        outer.addWidget(self.header)

        # Split layout: left column = list of blocks, right column = editor
        splitter = QSplitter()
        splitter.setHandleWidth(8)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_editor())
        splitter.setSizes([300, 900])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)

        self._reload_list()
        if self.list.count() > 0:
            self.list.setCurrentRow(0)

    # ---------- layout helpers ----------
    def _build_left_panel(self) -> QWidget:
        card = Card("Your blocks", "Select one to edit")
        card.setMinimumWidth(260)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(False)
        self.list.itemSelectionChanged.connect(self._on_selection)
        card.addWidget(self.list, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        dup_btn = QPushButton("Duplicate")
        del_btn = QPushButton("Delete")
        del_btn.setProperty("variant", "danger")
        dup_btn.clicked.connect(self._duplicate_block)
        del_btn.clicked.connect(self._delete_block)
        btn_row.addWidget(dup_btn)
        btn_row.addWidget(del_btn)
        card.addLayout(btn_row)
        return card

    def _build_editor(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # ---- top card: name + status + lock ----
        top = Card()
        row = QHBoxLayout()
        row.setSpacing(10)

        label_name = QLabel("Name")
        label_name.setStyleSheet(
            f"color:{Colors.TEXT_MUTED};font-size:11px;font-weight:700;letter-spacing:1px;"
        )
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Deep work")
        self.name_edit.setMinimumHeight(36)
        self.name_edit.editingFinished.connect(self._save_name)
        name_col = QVBoxLayout()
        name_col.setSpacing(4)
        name_col.addWidget(label_name)
        name_col.addWidget(self.name_edit)
        row.addLayout(name_col, 1)

        # Enable toggle
        self.enabled_btn = QPushButton("Enable")
        self.enabled_btn.setProperty("variant", "toggle")
        self.enabled_btn.setCheckable(True)
        self.enabled_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.enabled_btn.setMinimumHeight(36)
        self.enabled_btn.clicked.connect(self._toggle_enabled)

        self.status_pill = StatusPill("INACTIVE", StatusPill.KIND_OFF)
        status_col = QVBoxLayout()
        status_col.setSpacing(4)
        status_col.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_lbl = QLabel("Status")
        status_lbl.setStyleSheet(
            f"color:{Colors.TEXT_MUTED};font-size:11px;font-weight:700;letter-spacing:1px;"
        )
        status_col.addWidget(status_lbl)
        status_col.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignLeft)
        row.addLayout(status_col)

        row.addWidget(self.enabled_btn)
        top.addLayout(row)

        # Lock row
        lock_row = QHBoxLayout()
        self.lock_info = QLabel("No lock")
        self.lock_info.setStyleSheet(f"color:{Colors.TEXT_MUTED};")
        lock_row.addWidget(self.lock_info, 1)
        self.lock_btn = QPushButton("Configure lock")
        self.lock_btn.clicked.connect(self._configure_lock)
        lock_row.addWidget(self.lock_btn)
        top.addLayout(lock_row)
        v.addWidget(top)

        # ---- sub-tabs ----
        sub = QTabWidget()
        sub.addTab(self._build_sites_tab(), "Websites")
        sub.addTab(self._build_apps_tab(), "Applications")
        sub.addTab(self._build_allowance_tab(), "Allowance")
        sub.addTab(self._build_warning_tab(), "Warning")
        sub.addTab(self._build_users_tab(), "Users")
        v.addWidget(sub, 1)
        return wrap

    def _build_sites_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 10, 0, 0)
        v.setSpacing(12)

        help_card = Card(
            "Pattern reference",
            "One rule per line. Wildcards (*) are allowed.",
        )
        examples = QLabel(
            "facebook.com                 domain + all subdomains & mobile\n"
            "reddit.com/r/funny           specific path\n"
            "youtube.com/mkbhd            YouTube channel\n"
            "google.com/*q=*unicorn*      wildcard search block\n"
            "*.*                          block the entire internet"
        )
        examples.setStyleSheet(
            f"color:{Colors.TEXT_MUTED};font-family:'Cascadia Mono',Consolas,monospace;"
            f"font-size:12px;background:{Colors.BG};padding:10px;border-radius:8px;"
            f"border:1px solid {Colors.BORDER};"
        )
        help_card.addWidget(examples)
        v.addWidget(help_card)

        # Editors side by side
        row_card = Card()
        inner = QHBoxLayout()
        inner.setSpacing(12)

        self.sites_edit = QPlainTextEdit()
        self.sites_edit.setPlaceholderText("Blocked patterns, one per line...")
        self.sites_excepts_edit = QPlainTextEdit()
        self.sites_excepts_edit.setPlaceholderText("Exceptions (leave empty for none)...")
        self.sites_edit.textChanged.connect(self._save_sites)
        self.sites_excepts_edit.textChanged.connect(self._save_sites)

        def col(title: str, widget: QWidget) -> QWidget:
            c = QWidget()
            cv = QVBoxLayout(c); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(6)
            lt = QLabel(title.upper())
            lt.setStyleSheet(
                f"color:{Colors.TEXT_MUTED};font-size:11px;font-weight:700;"
                f"letter-spacing:1px;"
            )
            cv.addWidget(lt)
            cv.addWidget(widget, 1)
            return c

        inner.addWidget(col("Blocked patterns", self.sites_edit), 1)
        inner.addWidget(col("Exceptions", self.sites_excepts_edit), 1)
        row_card.addLayout(inner)

        btn_row = QHBoxLayout()
        add_default = QPushButton("Add default distractions")
        import_btn = QPushButton("Import...")
        export_btn = QPushButton("Export...")
        add_default.clicked.connect(self._add_default_distractions)
        import_btn.clicked.connect(self._import_sites)
        export_btn.clicked.connect(self._export_sites)
        btn_row.addWidget(add_default); btn_row.addWidget(import_btn)
        btn_row.addWidget(export_btn); btn_row.addStretch(1)
        row_card.addLayout(btn_row)

        v.addWidget(row_card, 1)
        return w

    def _build_apps_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 10, 0, 0)
        v.setSpacing(12)

        # Files
        files_card = Card(
            "Block executables",
            "Selected .exe files cannot launch while this block is active.",
        )
        self.files_list = QListWidget()
        self.files_list.setMinimumHeight(100)
        files_card.addWidget(self.files_list)
        fr = QHBoxLayout()
        add_file = QPushButton("+ Add .exe")
        add_file.setProperty("variant", "primary")
        rem_file = QPushButton("Remove")
        rem_file.setProperty("variant", "danger")
        add_file.clicked.connect(self._add_exe)
        rem_file.clicked.connect(lambda: self._remove_selected(self.files_list, "app_files"))
        fr.addWidget(add_file); fr.addWidget(rem_file); fr.addStretch(1)
        files_card.addLayout(fr)
        v.addWidget(files_card)

        # Folders
        folders_card = Card(
            "Block folders",
            "Every .exe inside the folder (recursively) is blocked.",
        )
        self.folders_list = QListWidget()
        self.folders_list.setMinimumHeight(90)
        folders_card.addWidget(self.folders_list)
        r2 = QHBoxLayout()
        add_folder = QPushButton("+ Add folder")
        add_folder.setProperty("variant", "primary")
        rem_folder = QPushButton("Remove")
        rem_folder.setProperty("variant", "danger")
        add_folder.clicked.connect(self._add_folder)
        rem_folder.clicked.connect(lambda: self._remove_selected(self.folders_list, "app_folders"))
        r2.addWidget(add_folder); r2.addWidget(rem_folder); r2.addStretch(1)
        folders_card.addLayout(r2)
        v.addWidget(folders_card)

        # Window titles
        wt_card = Card(
            "Block by window title",
            "Substring matching. One phrase per line.",
        )
        self.windows_edit = QPlainTextEdit()
        self.windows_edit.setPlaceholderText("e.g. Solitaire")
        self.windows_edit.setFixedHeight(90)
        self.windows_edit.textChanged.connect(self._save_windows)
        wt_card.addWidget(self.windows_edit)
        v.addWidget(wt_card)

        # Store apps
        store_card = Card(
            "Microsoft Store / UWP apps",
            "Scan your installed Store apps and pick the ones to block.",
        )
        self.store_list = QListWidget()
        self.store_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.store_list.setMinimumHeight(100)
        store_card.addWidget(self.store_list)
        s_row = QHBoxLayout()
        scan_btn = QPushButton("Scan installed apps")
        save_store_btn = QPushButton("Save selection")
        save_store_btn.setProperty("variant", "primary")
        scan_btn.clicked.connect(self._scan_store_apps)
        save_store_btn.clicked.connect(self._save_store_selection)
        s_row.addWidget(scan_btn); s_row.addWidget(save_store_btn); s_row.addStretch(1)
        store_card.addLayout(s_row)
        v.addWidget(store_card)

        v.addStretch(1)
        return w

    def _build_allowance_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 10, 0, 0)
        v.setSpacing(12)

        card = Card(
            "Daily allowance",
            "Grant yourself a limited time each day. Resets at midnight.",
        )
        f = QFormLayout()
        f.setSpacing(10)
        self.allow_per_day = QSpinBox()
        self.allow_per_day.setRange(0, 24 * 60)
        self.allow_per_day.setSuffix(" min / day")
        self.allow_left = QLabel("0 min")
        self.allow_left.setStyleSheet(
            f"color:{Colors.SUCCESS};font-weight:700;font-size:14px;"
        )
        f.addRow("Minutes per day:", self.allow_per_day)
        f.addRow("Remaining today:", self.allow_left)
        card.addLayout(f)

        row = QHBoxLayout()
        self.allow_save_btn = QPushButton("Save")
        self.allow_save_btn.setProperty("variant", "primary")
        self.allow_grant_btn = QPushButton("Grant +10 min")
        self.allow_save_btn.clicked.connect(self._save_allowance)
        self.allow_grant_btn.clicked.connect(lambda: self._grant_extra(10))
        row.addWidget(self.allow_save_btn)
        row.addWidget(self.allow_grant_btn)
        row.addStretch(1)
        card.addLayout(row)
        v.addWidget(card)

        cause = Card(
            "Pause for a cause",
            "Donate (optional) and grant yourself 10 extra minutes.",
        )
        self.pause_btn = QPushButton("Donate to WWF and grant +10 min")
        self.pause_btn.clicked.connect(self._pause_for_cause)
        cause.addWidget(self.pause_btn)
        v.addWidget(cause)

        v.addStretch(1)
        return w

    def _build_warning_tab(self) -> QWidget:
        from ..widgets import PageScroll
        scroll = PageScroll()
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 10, 0, 0)
        v.setSpacing(12)

        # ---- Enable + preset ----
        head_card = Card(
            "Warning for this block",
            "Show a custom popup (and optional sound) when this block becomes "
            "active - on manual enable, a schedule start, a Pomodoro work phase, "
            "or when an allowance runs out.",
        )
        self.warning_enabled = QCheckBox("Enable warning for this block")
        head_card.addWidget(self.warning_enabled)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.warning_preset = DataComboBox()
        self.warning_preset.addOption("Choose a preset…", "")
        for key in WARNING_PRESETS:
            self.warning_preset.addOption(key.replace("_", " ").title(), key)
        preset_row.addWidget(self.warning_preset, 1)
        apply_preset_btn = QPushButton("Apply preset")
        apply_preset_btn.clicked.connect(self._apply_preset)
        preset_row.addWidget(apply_preset_btn)
        head_card.addLayout(preset_row)
        v.addWidget(head_card)

        # ---- Message ----
        msg_card = Card(
            "Message",
            "Shown in large text. Enter several lines to pick one at random.",
        )
        self.warning_message = QPlainTextEdit()
        self.warning_message.setPlaceholderText("GET OFF YOUTUBE AND GO REVISE")
        self.warning_message.setFixedHeight(90)
        msg_card.addWidget(self.warning_message)
        v.addWidget(msg_card)

        # ---- Sound ----
        sound_card = Card("Sound", "Optional. MP3, WAV or OGG.")
        sound_row = QHBoxLayout()
        self.warning_sound_path = QLineEdit()
        self.warning_sound_path.setPlaceholderText(r"C:\Sounds\scream.mp3")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_warning_sound)
        test_sound_btn = QPushButton("Test sound")
        test_sound_btn.clicked.connect(self._test_warning_sound)
        sound_row.addWidget(self.warning_sound_path, 1)
        sound_row.addWidget(browse_btn)
        sound_row.addWidget(test_sound_btn)
        sound_card.addLayout(sound_row)

        builtin_row = QHBoxLayout()
        builtin_row.addWidget(QLabel("Built-in:"))
        self.warning_builtin_sound = DataComboBox()
        for name in builtin_sound_names():
            self.warning_builtin_sound.addOption(name.title(), name)
        use_builtin = QPushButton("Use built-in sound")
        use_builtin.clicked.connect(self._use_builtin_sound)
        builtin_row.addWidget(self.warning_builtin_sound, 1)
        builtin_row.addWidget(use_builtin)
        sound_card.addLayout(builtin_row)

        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("Volume:"))
        self.warning_volume = QSlider(Qt.Orientation.Horizontal)
        self.warning_volume.setRange(0, 100)
        self.warning_volume.setValue(80)
        self._warning_volume_label = QLabel("80%")
        self._warning_volume_label.setMinimumWidth(40)
        self.warning_volume.valueChanged.connect(
            lambda val: self._warning_volume_label.setText(f"{val}%")
        )
        vol_row.addWidget(self.warning_volume, 1)
        vol_row.addWidget(self._warning_volume_label)
        sound_card.addLayout(vol_row)

        audio_opts = QHBoxLayout()
        self.warning_loop_sound = QCheckBox("Loop until popup closes")
        audio_opts.addWidget(self.warning_loop_sound)
        audio_opts.addWidget(QLabel("Stop after"))
        self.warning_sound_max = QSpinBox()
        self.warning_sound_max.setRange(0, 600)
        self.warning_sound_max.setSuffix(" s (0 = full)")
        audio_opts.addWidget(self.warning_sound_max)
        audio_opts.addStretch(1)
        sound_card.addLayout(audio_opts)
        v.addWidget(sound_card)

        # ---- Popup behaviour ----
        popup_card = Card("Popup", "How it looks, how long it shows and how it closes.")
        form = QFormLayout()
        form.setSpacing(10)

        self.warning_popup_mode = DataComboBox()
        self.warning_popup_mode.addOption("Centered", "centered")
        self.warning_popup_mode.addOption("Compact (corner)", "compact")
        self.warning_popup_mode.addOption("Full screen", "fullscreen")
        form.addRow("Popup mode:", self.warning_popup_mode)

        self.warning_duration = QSpinBox()
        self.warning_duration.setRange(1, 3600)
        self.warning_duration.setValue(8)
        self.warning_duration.setSuffix(" s")
        form.addRow("Visible for:", self.warning_duration)

        self.warning_repeat_minutes = QSpinBox()
        self.warning_repeat_minutes.setRange(0, 1440)
        self.warning_repeat_minutes.setSuffix(" min (0 = once)")
        form.addRow("Repeat every:", self.warning_repeat_minutes)

        image_row = QHBoxLayout()
        self.warning_image_path = QLineEdit()
        self.warning_image_path.setPlaceholderText("Optional image or .gif")
        image_browse = QPushButton("Browse…")
        image_browse.clicked.connect(self._browse_warning_image)
        image_row.addWidget(self.warning_image_path, 1)
        image_row.addWidget(image_browse)
        image_w = QWidget(); image_w.setLayout(image_row)
        form.addRow("Image / GIF:", image_w)

        fade_row = QHBoxLayout()
        self.warning_fade_enabled = QCheckBox("Fade out")
        self.warning_fade_seconds = QSpinBox()
        self.warning_fade_seconds.setRange(0, 60)
        self.warning_fade_seconds.setValue(2)
        self.warning_fade_seconds.setSuffix(" s")
        fade_row.addWidget(self.warning_fade_enabled)
        fade_row.addWidget(QLabel("over"))
        fade_row.addWidget(self.warning_fade_seconds)
        fade_row.addStretch(1)
        fade_w = QWidget(); fade_w.setLayout(fade_row)
        form.addRow("Fade:", fade_w)

        self.warning_always_on_top = QCheckBox("Always on top")
        form.addRow("Window:", self.warning_always_on_top)

        self.warning_theme = DataComboBox()
        for label, data in (
            ("Default", "default"), ("Red alert", "red_alert"),
            ("Calm", "calm"), ("Exam", "exam"),
            ("Minimal", "minimal"), ("High contrast", "high_contrast"),
        ):
            self.warning_theme.addOption(label, data)
        form.addRow("Theme:", self.warning_theme)

        self.warning_dismiss_mode = DataComboBox()
        self.warning_dismiss_mode.addOption("Auto-close", "auto_close")
        self.warning_dismiss_mode.addOption("Click to close", "click_to_close")
        self.warning_dismiss_mode.addOption("Type to dismiss", "type_to_dismiss")
        self.warning_dismiss_mode.addOption("Hold to dismiss", "hold_to_dismiss")
        form.addRow("Dismiss mode:", self.warning_dismiss_mode)

        strict_row = QHBoxLayout()
        strict_row.addWidget(QLabel("Close button after"))
        self.warning_close_delay = QSpinBox()
        self.warning_close_delay.setRange(0, 600)
        self.warning_close_delay.setSuffix(" s")
        strict_row.addWidget(self.warning_close_delay)
        strict_row.addWidget(QLabel("Hold for"))
        self.warning_hold_seconds = QSpinBox()
        self.warning_hold_seconds.setRange(1, 60)
        self.warning_hold_seconds.setValue(2)
        self.warning_hold_seconds.setSuffix(" s")
        strict_row.addWidget(self.warning_hold_seconds)
        strict_row.addStretch(1)
        strict_w = QWidget(); strict_w.setLayout(strict_row)
        form.addRow("Strict:", strict_w)
        popup_card.addLayout(form)
        v.addWidget(popup_card)

        # ---- Extra triggers ----
        trig_card = Card(
            "Extra triggers",
            "Beyond block activation, also warn on these events.",
        )
        self.warning_on_lock_unlock = QCheckBox("When a timer lock finishes")
        self.warning_on_early_unlock = QCheckBox("When a locked disable attempt is blocked")
        trig_card.addWidget(self.warning_on_lock_unlock)
        trig_card.addWidget(self.warning_on_early_unlock)
        v.addWidget(trig_card)

        # ---- Actions ----
        btn_row = QHBoxLayout()
        test_btn = QPushButton("Test warning")
        test_btn.clicked.connect(self._test_warning)
        export_btn = QPushButton("Export…")
        export_btn.clicked.connect(self._export_warning_profile)
        import_btn = QPushButton("Import…")
        import_btn.clicked.connect(self._import_warning_profile)
        save_btn = QPushButton("Save")
        save_btn.setProperty("variant", "primary")
        save_btn.clicked.connect(self._save_warning_and_notify)
        btn_row.addWidget(test_btn)
        btn_row.addWidget(export_btn)
        btn_row.addWidget(import_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(save_btn)
        v.addLayout(btn_row)
        v.addStretch(1)

        scroll.setWidget(w)
        return scroll

    def _build_users_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 10, 0, 0)

        card = Card(
            "Restrict to specific Windows users",
            "Leave empty to apply this block to every account. Otherwise, "
            "list usernames (one per line) that should be affected.",
        )
        self.users_edit = QPlainTextEdit()
        self.users_edit.setPlaceholderText("username\nanother_user")
        self.users_edit.textChanged.connect(self._save_users)
        card.addWidget(self.users_edit, 1)
        v.addWidget(card, 1)
        return w

    # ---------- selection/data binding ----------
    def _reload_list(self) -> None:
        self.list.clear()
        for b in self.engine.config.blocks:
            marker = "\u25CF  " if b.enabled else "\u25CB  "
            item = QListWidgetItem(f"{marker}{b.name}")
            if b.enabled:
                item.setForeground(Qt.GlobalColor.white)
            self.list.addItem(item)

    def _on_selection(self) -> None:
        row = self.list.currentRow()
        if row < 0 or row >= len(self.engine.config.blocks):
            self._current = None
            return
        self._current = self.engine.config.blocks[row]
        self._populate_from_current()

    def _populate_from_current(self) -> None:
        b = self._current
        if not b:
            return
        self.name_edit.blockSignals(True); self.name_edit.setText(b.name); self.name_edit.blockSignals(False)
        self.enabled_btn.blockSignals(True)
        self.enabled_btn.setChecked(b.enabled)
        self.enabled_btn.setText("ENABLED" if b.enabled else "ENABLE")
        self.enabled_btn.blockSignals(False)
        if b.enabled:
            self.status_pill.setText("ACTIVE")
            self.status_pill.set_kind(StatusPill.KIND_OK)
        else:
            self.status_pill.setText("INACTIVE")
            self.status_pill.set_kind(StatusPill.KIND_OFF)
        self.lock_info.setText("Lock: " + describe_lock(b.lock))

        self.sites_edit.blockSignals(True)
        self.sites_edit.setPlainText("\n".join(b.sites))
        self.sites_edit.blockSignals(False)
        self.sites_excepts_edit.blockSignals(True)
        self.sites_excepts_edit.setPlainText("\n".join(b.site_exceptions))
        self.sites_excepts_edit.blockSignals(False)

        self.files_list.clear(); self.files_list.addItems(b.app_files)
        self.folders_list.clear(); self.folders_list.addItems(b.app_folders)
        self.windows_edit.blockSignals(True)
        self.windows_edit.setPlainText("\n".join(b.app_windows))
        self.windows_edit.blockSignals(False)

        self.allow_per_day.setValue(b.allowance.minutes_per_day)
        self.allow_left.setText(f"{b.allowance.minutes_left_today} min")

        self.users_edit.blockSignals(True)
        self.users_edit.setPlainText("\n".join(b.users))
        self.users_edit.blockSignals(False)

        self._populate_warning()

    def _populate_warning(self) -> None:
        b = self._current
        if not b:
            return
        w = b.warning
        self.warning_enabled.setChecked(w.enabled)
        # Multi-line message pool shows joined; a single message shows as-is.
        if w.messages:
            self.warning_message.setPlainText("\n".join(w.messages))
        else:
            self.warning_message.setPlainText(w.message)
        self.warning_sound_path.setText(w.sound_path)
        self.warning_volume.setValue(int(w.volume))
        self._warning_volume_label.setText(f"{int(w.volume)}%")
        self.warning_duration.setValue(int(w.popup_duration_seconds))
        self.warning_fade_enabled.setChecked(w.fade_enabled)
        self.warning_fade_seconds.setValue(int(w.fade_seconds))
        self.warning_always_on_top.setChecked(w.always_on_top)
        self.warning_theme.setCurrentData(w.theme or "default")
        self.warning_dismiss_mode.setCurrentData(w.dismiss_mode or "auto_close")
        self.warning_popup_mode.setCurrentData(w.popup_mode or "centered")
        self.warning_image_path.setText(w.image_path)
        self.warning_loop_sound.setChecked(w.loop_sound)
        self.warning_sound_max.setValue(int(w.sound_max_seconds))
        self.warning_close_delay.setValue(int(w.close_delay_seconds))
        self.warning_hold_seconds.setValue(int(w.hold_seconds))
        self.warning_repeat_minutes.setValue(int(w.repeat_minutes))
        self.warning_on_lock_unlock.setChecked(w.on_lock_unlock)
        self.warning_on_early_unlock.setChecked(w.on_early_unlock)
        self.warning_preset.setCurrentData("")

    # ---------- list ops ----------
    def _new_block(self) -> None:
        name, ok = QInputDialog.getText(self, "New block", "Name:")
        if not ok or not name.strip():
            return
        self.engine.config.blocks.append(BlockList(name=name.strip()))
        self.engine.save()
        self._reload_list()
        self.list.setCurrentRow(len(self.engine.config.blocks) - 1)

    def _duplicate_block(self) -> None:
        if not self._current:
            return
        import copy
        clone = copy.deepcopy(self._current)
        clone.name = self._current.name + " (copy)"
        clone.enabled = False
        self.engine.config.blocks.append(clone)
        self.engine.save()
        self._reload_list()

    def _delete_block(self) -> None:
        if not self._current:
            return
        ok, reason = can_disable(self._current)
        if not ok and self._current.enabled:
            error(self, "This block is locked and cannot be deleted:\n\n" + reason)
            return
        if not confirm(self, f"Delete '{self._current.name}'?"):
            return
        self.engine.config.blocks.remove(self._current)
        self.engine.save()
        self._current = None
        self._reload_list()

    # ---------- save helpers ----------
    def _save_name(self) -> None:
        if not self._current:
            return
        new = self.name_edit.text().strip()
        if new and new != self._current.name:
            self._current.name = new
            self.engine.save()
            self._reload_list()

    def _toggle_enabled(self) -> None:
        if not self._current:
            return
        want = self.enabled_btn.isChecked()
        if not want and self._current.enabled:
            ok, reason = can_disable(self._current)
            if not ok:
                if self._current.lock.kind == "random":
                    expected = random_unlock_text(self._current.lock.random_length)
                    info(self, "Type the following string EXACTLY to unlock.\n\n" + expected)
                    from PyQt6.QtWidgets import QInputDialog as D
                    typed, go = D.getText(self, "Random unlock", "Enter the text:")
                    if not go or typed != expected:
                        self._report_unlock_blocked()
                        error(self, "Unlock text did not match.")
                        self.enabled_btn.setChecked(True)
                        return
                elif self._current.lock.kind == "password":
                    from PyQt6.QtWidgets import QInputDialog as D
                    pwd, go = D.getText(
                        self, "Password", "Password:",
                        QLineEdit.EchoMode.Password,
                    )
                    if not go:
                        self.enabled_btn.setChecked(True); return
                    ok2, reason2 = can_disable(self._current, password_attempt=pwd)
                    if not ok2:
                        self._report_unlock_blocked()
                        error(self, reason2); self.enabled_btn.setChecked(True); return
                else:
                    self._report_unlock_blocked()
                    error(self, reason)
                    self.enabled_btn.setChecked(True)
                    return
        self.engine.set_block_enabled(self._current.name, want)
        self._reload_list()
        self._populate_from_current()

    def _report_unlock_blocked(self) -> None:
        """Tell the engine an early-unlock attempt was blocked (may fire a warning)."""
        if self._current and hasattr(self.engine, "report_unlock_blocked"):
            try:
                self.engine.report_unlock_blocked(self._current.name)
            except Exception:
                pass

    def _configure_lock(self) -> None:
        if not self._current:
            return
        if self._current.enabled:
            ok, reason = can_disable(self._current)
            if not ok:
                error(self, "Block is locked. You can only tighten a lock while active:\n\n" + reason)
                return
        dlg = _LockEditor(self, self._current.lock)
        if dlg.exec():
            self._current.lock = dlg.lock
            self.engine.save()
            self.lock_info.setText("Lock: " + describe_lock(self._current.lock))

    def _save_sites(self) -> None:
        if not self._current:
            return
        self._current.sites = [
            l.strip() for l in self.sites_edit.toPlainText().splitlines() if l.strip()
        ]
        self._current.site_exceptions = [
            l.strip() for l in self.sites_excepts_edit.toPlainText().splitlines() if l.strip()
        ]
        self.engine.save()

    def _save_windows(self) -> None:
        if not self._current:
            return
        self._current.app_windows = [
            l.strip() for l in self.windows_edit.toPlainText().splitlines() if l.strip()
        ]
        self.engine.save()

    def _save_users(self) -> None:
        if not self._current:
            return
        self._current.users = [
            l.strip() for l in self.users_edit.toPlainText().splitlines() if l.strip()
        ]
        self.engine.save()

    def _save_allowance(self) -> None:
        if not self._current:
            return
        self._current.allowance.minutes_per_day = self.allow_per_day.value()
        if self._current.allowance.minutes_left_today < self._current.allowance.minutes_per_day:
            self._current.allowance.minutes_left_today = self._current.allowance.minutes_per_day
        if not self._current.allowance.last_reset:
            self._current.allowance.last_reset = dt.date.today().isoformat()
        self.engine.save()
        self.allow_left.setText(f"{self._current.allowance.minutes_left_today} min")

    def _grant_extra(self, minutes: int) -> None:
        if not self._current:
            return
        self.engine.grant_allowance(self._current.name, minutes)
        self.allow_left.setText(f"{self._current.allowance.minutes_left_today} min")

    def _pause_for_cause(self) -> None:
        if not self._current:
            return
        import webbrowser
        if confirm(self, "This will open the World Wildlife Fund donation page "
                         "and grant you a 10-minute break. Continue?"):
            try:
                webbrowser.open("https://www.worldwildlife.org/donate")
            except Exception:
                pass
            self._grant_extra(10)
            info(self, "Thank you! 10 minutes granted.")

    # ---------- warning ----------
    def _warning_from_widgets(self) -> WarningConfig:
        """Build a WarningConfig from the current widget values (no save)."""
        lines = [
            l.strip() for l in self.warning_message.toPlainText().splitlines()
            if l.strip()
        ]
        messages = lines if len(lines) > 1 else []
        message = lines[0] if lines else ""
        return WarningConfig(
            enabled=self.warning_enabled.isChecked(),
            message=message,
            sound_path=self.warning_sound_path.text().strip(),
            volume=self.warning_volume.value(),
            popup_duration_seconds=self.warning_duration.value(),
            fade_enabled=self.warning_fade_enabled.isChecked(),
            fade_seconds=self.warning_fade_seconds.value(),
            always_on_top=self.warning_always_on_top.isChecked(),
            dismiss_mode=self.warning_dismiss_mode.currentData() or "auto_close",
            messages=messages,
            theme=self.warning_theme.currentData() or "default",
            popup_mode=self.warning_popup_mode.currentData() or "centered",
            image_path=self.warning_image_path.text().strip(),
            loop_sound=self.warning_loop_sound.isChecked(),
            sound_max_seconds=self.warning_sound_max.value(),
            close_delay_seconds=self.warning_close_delay.value(),
            hold_seconds=self.warning_hold_seconds.value(),
            repeat_minutes=self.warning_repeat_minutes.value(),
            on_lock_unlock=self.warning_on_lock_unlock.isChecked(),
            on_early_unlock=self.warning_on_early_unlock.isChecked(),
        )

    def _save_warning(self) -> None:
        """Persist the Warning tab into the selected block's nested config."""
        if not self._current:
            return
        self._current.warning = self._warning_from_widgets()
        self.engine.save()

    def _save_warning_and_notify(self) -> None:
        if not self._current:
            return
        self._save_warning()
        info(self, "Warning settings saved.")

    def _apply_preset(self) -> None:
        if not self._current:
            return
        name = self.warning_preset.currentData()
        if not name:
            return
        # Start from the current widget state so the user keeps their tweaks,
        # then let the preset fill the rest. Stays editable until saved.
        cfg = self._warning_from_widgets()
        try:
            sounds = ensure_builtin_sounds()
        except Exception:
            sounds = {}
        apply_warning_preset(cfg, name, sounds=sounds)
        self._current.warning = cfg
        self._populate_warning()

    def _browse_warning_sound(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose warning sound",
            filter="Audio (*.mp3 *.wav *.ogg);;All files (*)",
        )
        if path:
            self.warning_sound_path.setText(path)

    def _browse_warning_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose warning image",
            filter="Images (*.png *.jpg *.jpeg *.gif *.bmp);;All files (*)",
        )
        if path:
            self.warning_image_path.setText(path)

    def _use_builtin_sound(self) -> None:
        name = self.warning_builtin_sound.currentData()
        if not name:
            return
        try:
            sounds = ensure_builtin_sounds()
        except Exception:
            sounds = {}
        path = sounds.get(name)
        if path:
            self.warning_sound_path.setText(path)
        else:
            error(self, "Could not create the built-in sound (needs write access).")

    def _export_warning_profile(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export warning profile", "warning.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(asdict(self._warning_from_widgets()), indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            error(self, str(e))

    def _import_warning_profile(self) -> None:
        if not self._current:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import warning profile", filter="JSON (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            error(self, str(e))
            return
        if not isinstance(data, dict):
            error(self, "That file is not a warning profile.")
            return
        self._current.warning = WarningConfig(**_only_known(WarningConfig, data))
        self._populate_warning()
        self.engine.save()

    def _ensure_warning_manager(self):
        if self._warning_manager is None:
            from ..warning_popup import WarningManager
            self._warning_manager = WarningManager(parent=self)
        return self._warning_manager

    def _test_warning(self) -> None:
        """Preview the current Warning tab settings without changing state."""
        cfg = self._warning_from_widgets()
        try:
            self._ensure_warning_manager().test_warning(cfg)
        except Exception as e:
            error(self, f"Could not show the warning popup:\n\n{e}")

    def _test_warning_sound(self) -> None:
        """Play just the chosen sound, reporting failures (report §8.1, §18.2)."""
        path = self.warning_sound_path.text().strip()
        if not path:
            error(self, "Choose a sound file first.")
            return
        if not os.path.isfile(path):
            error(self, "Sound file not found:\n\n" + path)
            return
        try:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
            if not hasattr(self, "_sound_test_player"):
                self._sound_test_player = QMediaPlayer(self)
                self._sound_test_audio = QAudioOutput(self)
                self._sound_test_player.setAudioOutput(self._sound_test_audio)
            self._sound_test_audio.setVolume(self.warning_volume.value() / 100.0)
            self._sound_test_player.setSource(QUrl.fromLocalFile(path))
            self._sound_test_player.play()
        except Exception as e:
            error(self, f"Could not play the sound:\n\n{e}")

    # ---------- sites buttons ----------
    def _add_default_distractions(self) -> None:
        if not self._current:
            return
        existing = set(self._current.sites)
        for d in DEFAULT_DISTRACTIONS:
            if d not in existing:
                self._current.sites.append(d)
        self.engine.save()
        self._populate_from_current()

    def _import_sites(self) -> None:
        if not self._current:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import list",
                                              filter="Text/JSON (*.txt *.json);;All files (*)")
        if not path:
            return
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except Exception as e:
            error(self, str(e)); return
        items: list[str] = []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                items = [str(x) for x in data]
            elif isinstance(data, dict) and "sites" in data:
                items = [str(x) for x in data["sites"]]
        except Exception:
            items = [l.strip() for l in raw.splitlines() if l.strip() and not l.strip().startswith("#")]
        for it in items:
            if it not in self._current.sites:
                self._current.sites.append(it)
        self.engine.save()
        self._populate_from_current()

    def _export_sites(self) -> None:
        if not self._current:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export list",
                                              self._current.name + ".json",
                                              "JSON (*.json);;Text (*.txt)")
        if not path:
            return
        try:
            if path.lower().endswith(".json"):
                Path(path).write_text(json.dumps({
                    "name": self._current.name,
                    "sites": self._current.sites,
                    "exceptions": self._current.site_exceptions,
                }, indent=2), encoding="utf-8")
            else:
                Path(path).write_text("\n".join(self._current.sites), encoding="utf-8")
        except Exception as e:
            error(self, str(e))

    # ---------- apps buttons ----------
    def _add_exe(self) -> None:
        if not self._current:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select .exe", filter="Executables (*.exe)")
        if not path:
            return
        if path not in self._current.app_files:
            self._current.app_files.append(path)
        self.engine.save()
        self._populate_from_current()

    def _add_folder(self) -> None:
        if not self._current:
            return
        path = QFileDialog.getExistingDirectory(self, "Select folder")
        if not path:
            return
        if path not in self._current.app_folders:
            self._current.app_folders.append(path)
        self.engine.save()
        self._populate_from_current()

    def _remove_selected(self, list_widget: QListWidget, attr: str) -> None:
        if not self._current:
            return
        items = [i.text() for i in list_widget.selectedItems()]
        cur = getattr(self._current, attr)
        setattr(self._current, attr, [x for x in cur if x not in items])
        self.engine.save()
        self._populate_from_current()

    def _scan_store_apps(self) -> None:
        from ...blocking.apps import list_store_apps
        apps = list_store_apps()
        self.store_list.clear()
        selected = set((self._current.store_apps if self._current else []))
        for a in apps:
            item = QListWidgetItem(a)
            if a in selected:
                item.setSelected(True)
            self.store_list.addItem(item)
        if not apps:
            info(self, "No UWP apps found (PowerShell may be unavailable).")

    def _save_store_selection(self) -> None:
        if not self._current:
            return
        self._current.store_apps = [i.text() for i in self.store_list.selectedItems()]
        self.engine.save()
