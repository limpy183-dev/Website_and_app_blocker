"""Pomodoro configuration."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from ...engine import Engine
from ..common import info
from ..theme import Colors
from ..widgets import Card, PageHeader


class PomodoroTab(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        self.header = PageHeader(
            "Pomodoro",
            "Alternate focused work intervals with restorative breaks."
        )
        save_btn = QPushButton("Save")
        save_btn.setProperty("variant", "primary")
        start_btn = QPushButton("Start now")
        start_btn.setProperty("variant", "success")
        self.pause_btn = QPushButton("Pause")
        self.skip_btn = QPushButton("Skip phase")
        stop_btn = QPushButton("Stop")
        stop_btn.setProperty("variant", "danger")
        save_btn.clicked.connect(self._save)
        start_btn.clicked.connect(self._on_start)
        self.pause_btn.clicked.connect(self._on_pause)
        self.skip_btn.clicked.connect(self._on_skip)
        stop_btn.clicked.connect(self._on_stop)
        self.header.add_action(start_btn)
        self.header.add_action(self.pause_btn)
        self.header.add_action(self.skip_btn)
        self.header.add_action(stop_btn)
        self.header.add_action(save_btn)
        v.addWidget(self.header)

        # ---- Live countdown (report §3.9) ----
        timer_card = Card("Current session", "Live phase and time remaining.")
        self.timer_label = QLabel("Idle")
        self.timer_label.setStyleSheet(
            f"color:{Colors.TEXT};font-size:28px;font-weight:800;letter-spacing:1px;"
        )
        self.phase_label = QLabel("No Pomodoro running.")
        self.phase_label.setStyleSheet(f"color:{Colors.TEXT_MUTED};font-size:12px;")
        timer_card.addWidget(self.timer_label)
        timer_card.addWidget(self.phase_label)
        v.addWidget(timer_card)

        # Tick the live countdown once a second while this tab exists.
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._refresh_live)
        self._tick_timer.start()

        card = Card("Configuration", "All values apply to the next cycle you start.")

        self.enabled = QCheckBox("Enable pomodoro")
        card.addWidget(self.enabled)

        f = QFormLayout()
        f.setSpacing(12)
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.target = QComboBox()
        self.work = QSpinBox(); self.work.setRange(1, 240); self.work.setSuffix(" min")
        self.rest = QSpinBox(); self.rest.setRange(1, 240); self.rest.setSuffix(" min")
        self.cycles = QSpinBox(); self.cycles.setRange(1, 99)
        self.long_break = QSpinBox(); self.long_break.setRange(1, 240); self.long_break.setSuffix(" min")
        self.long_break_every = QSpinBox()
        self.long_break_every.setRange(0, 99)
        self.long_break_every.setSpecialValueText("Off")
        self.long_break_every.setPrefix("every ")
        self.long_break_every.setSuffix(" cycles")
        f.addRow("Target block:", self.target)
        f.addRow("Work interval:", self.work)
        f.addRow("Break interval:", self.rest)
        f.addRow("Cycles:", self.cycles)
        f.addRow("Long break:", self.long_break)
        f.addRow("Long break frequency:", self.long_break_every)
        card.addLayout(f)
        v.addWidget(card)

        # ---- Phase warnings (report §6.2) ----
        warn_card = Card(
            "Phase warnings",
            "Optionally show a popup (and sound) when the Pomodoro phase changes.",
        )
        self.phase_warnings = QCheckBox("Show a warning on each phase change")
        warn_card.addWidget(self.phase_warnings)

        wf = QFormLayout()
        wf.setSpacing(10)
        self.work_message = QLineEdit()
        self.break_message = QLineEdit()
        self.complete_message = QLineEdit()
        wf.addRow("Work start:", self.work_message)
        wf.addRow("Break start:", self.break_message)
        wf.addRow("Cycle complete:", self.complete_message)

        sound_row = QHBoxLayout()
        self.warn_sound = QLineEdit()
        self.warn_sound.setPlaceholderText("Optional sound file")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_sound)
        sound_row.addWidget(self.warn_sound, 1)
        sound_row.addWidget(browse)
        sound_w = QWidget(); sound_w.setLayout(sound_row)
        wf.addRow("Sound:", sound_w)

        vol_row = QHBoxLayout()
        self.warn_volume = QSlider(Qt.Orientation.Horizontal)
        self.warn_volume.setRange(0, 100)
        self.warn_volume.setValue(80)
        self._vol_label = QLabel("80%")
        self.warn_volume.valueChanged.connect(lambda x: self._vol_label.setText(f"{x}%"))
        vol_row.addWidget(self.warn_volume, 1)
        vol_row.addWidget(self._vol_label)
        vol_w = QWidget(); vol_w.setLayout(vol_row)
        wf.addRow("Volume:", vol_w)
        warn_card.addLayout(wf)
        v.addWidget(warn_card)

        hint = Card(
            "How it works",
            "During a work interval, your target block is ACTIVE. During a "
            "break, it automatically pauses. A standard pattern is 25 min "
            "work / 5 min rest across 4 cycles.",
        )
        v.addWidget(hint)
        v.addStretch(1)

        self._reload()

    def showEvent(self, e):
        self._reload()
        self._refresh_live()
        super().showEvent(e)

    def _reload(self) -> None:
        self.target.clear()
        for b in self.engine.config.blocks:
            self.target.addItem(b.name)
        p = self.engine.config.settings.pomodoro
        self.enabled.setChecked(p.enabled)
        if p.target_block:
            idx = self.target.findText(p.target_block)
            if idx >= 0:
                self.target.setCurrentIndex(idx)
        self.work.setValue(p.work_minutes)
        self.rest.setValue(p.break_minutes)
        self.cycles.setValue(p.cycles)
        self.long_break.setValue(int(getattr(p, "long_break_minutes", 15)))
        self.long_break_every.setValue(int(getattr(p, "long_break_every", 4)))
        self.phase_warnings.setChecked(p.phase_warnings)
        self.work_message.setText(p.work_message)
        self.break_message.setText(p.break_message)
        self.complete_message.setText(p.complete_message)
        self.warn_sound.setText(p.warning_sound_path)
        self.warn_volume.setValue(int(p.warning_volume))
        self._vol_label.setText(f"{int(p.warning_volume)}%")

    def _browse_sound(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose phase-warning sound",
            filter="Audio (*.mp3 *.wav *.ogg);;All files (*)",
        )
        if path:
            self.warn_sound.setText(path)

    def _save(self) -> None:
        p = self.engine.config.settings.pomodoro
        p.enabled = self.enabled.isChecked()
        p.target_block = self.target.currentText()
        p.work_minutes = self.work.value()
        p.break_minutes = self.rest.value()
        p.cycles = self.cycles.value()
        p.long_break_minutes = self.long_break.value()
        p.long_break_every = self.long_break_every.value()
        p.phase_warnings = self.phase_warnings.isChecked()
        p.work_message = self.work_message.text()
        p.break_message = self.break_message.text()
        p.complete_message = self.complete_message.text()
        p.warning_sound_path = self.warn_sound.text().strip()
        p.warning_volume = self.warn_volume.value()
        self.engine.save()
        info(self, "Pomodoro settings saved.")

    # ---- session controls ----
    def _on_start(self) -> None:
        # Persist current settings first so "Start now" uses them.
        p = self.engine.config.settings.pomodoro
        p.enabled = self.enabled.isChecked()
        p.target_block = self.target.currentText()
        p.work_minutes = self.work.value()
        p.break_minutes = self.rest.value()
        p.cycles = self.cycles.value()
        p.long_break_minutes = self.long_break.value()
        p.long_break_every = self.long_break_every.value()
        self.engine.save()
        self.engine.start_pomodoro()
        self._refresh_live()

    def _on_stop(self) -> None:
        self.engine.stop_pomodoro()
        self._refresh_live()

    def _on_pause(self) -> None:
        if self.engine.is_pomodoro_paused():
            self.engine.resume_pomodoro()
        else:
            self.engine.pause_pomodoro()
        self._refresh_live()

    def _on_skip(self) -> None:
        self.engine.skip_pomodoro_phase()
        self._refresh_live()

    @staticmethod
    def _fmt_mmss(seconds: int) -> str:
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        return f"{m:02d}:{s:02d}"

    def _refresh_live(self) -> None:
        try:
            status = self.engine.pomodoro_status()
        except Exception:
            status = None
        running = status is not None
        self.pause_btn.setEnabled(running)
        self.skip_btn.setEnabled(running)
        if not running:
            self.timer_label.setText("Idle")
            self.phase_label.setText("No Pomodoro running.")
            self.pause_btn.setText("Pause")
            return
        phase = {
            "work": "Work", "break": "Break", "long_break": "Long break",
        }.get(status["phase"], status["phase"].title())
        self.timer_label.setText(self._fmt_mmss(status["remaining_seconds"]))
        paused = " (paused)" if status.get("paused") else ""
        self.phase_label.setText(
            f"{phase}{paused} — cycle {status['cycle']} of {status['cycles']}"
        )
        self.pause_btn.setText("Resume" if status.get("paused") else "Pause")
