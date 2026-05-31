"""Warning popup presentation + audio (report §7, §8, §9, §16, §17, §19.5).

This is the only place that builds PyQt widgets / plays audio for warnings.
The engine emits data-only :class:`~focusfortress.engine.WarningEvent` objects;
:class:`WarningManager` turns one into a styled :class:`WarningPopup` on the
Qt main thread.

Supports:

* popup modes - centered / compact / full-screen (§7.2, §7.4)
* per-theme styling + colour overrides (§17), optional image/GIF (§19.5)
* audio with optional looping and a max-duration cap (§8.3); always fails safe
* dismiss modes - auto-close / click-to-close / type-to-dismiss / hold-to-dismiss,
  plus a "close button appears after N seconds" delay (§9, §16.2)
"""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QUrl, QPropertyAnimation, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QMovie, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from ..models import WarningConfig
from ..warnings import resolve_warning_message
from .theme import Colors

# QtMultimedia is optional - guard so the popup still works without it.
try:  # pragma: no cover - exercised at runtime, not in unit tests
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    _HAVE_AUDIO = True
except Exception:  # pragma: no cover
    QAudioOutput = None  # type: ignore
    QMediaPlayer = None  # type: ignore
    _HAVE_AUDIO = False


# Theme name -> {background, accent, text}. Distinct looks, not just an accent.
_THEMES = {
    "default":       {"bg": Colors.SURFACE, "accent": Colors.ACCENT,    "text": Colors.TEXT},
    "red_alert":     {"bg": "#2a0f12",      "accent": Colors.DANGER,    "text": "#ffe5e5"},
    "calm":          {"bg": "#0f1b22",      "accent": Colors.INFO,      "text": "#dff1fb"},
    "exam":          {"bg": "#241b08",      "accent": Colors.WARNING,   "text": "#fff2d6"},
    "minimal":       {"bg": Colors.SURFACE, "accent": Colors.BORDER_HI, "text": Colors.TEXT},
    "high_contrast": {"bg": "#000000",      "accent": "#ffffff",        "text": "#ffffff"},
}

# Font sizes per popup mode: (header, body)
_MODE_FONTS = {
    "compact":    (12, 18),
    "centered":   (14, 26),
    "fullscreen": (22, 46),
}


class WarningPopup(QDialog):
    """A single styled warning window (centered / compact / full-screen)."""

    #: emitted when the popup has fully closed (after any fade-out)
    closed = pyqtSignal()

    def __init__(
        self,
        config: WarningConfig,
        message: str,
        title: str = "FOCUS WARNING",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._closing = False
        self._player = None
        self._audio = None
        self._movie = None
        self._hold_timer = None

        self._mode = config.popup_mode if config.popup_mode in _MODE_FONTS else "centered"
        theme = dict(_THEMES.get(config.theme, _THEMES["default"]))
        if config.background_color:
            theme["bg"] = config.background_color
        if config.text_color:
            theme["text"] = config.text_color
        self._theme = theme

        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        if config.always_on_top or self._mode == "fullscreen":
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setModal(False)
        if self._mode == "compact":
            self.setMinimumWidth(360)
        elif self._mode == "centered":
            self.setMinimumWidth(520)

        self._build_ui(title, message)
        self._setup_audio()
        self._setup_dismiss()

    # ------------------------------------------------------------------ UI
    def _build_ui(self, title: str, message: str) -> None:
        header_pt, body_pt = _MODE_FONTS[self._mode]
        accent, bg, text = self._theme["accent"], self._theme["bg"], self._theme["text"]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("WarningCard")
        border = "none" if self._mode == "fullscreen" else f"2px solid {accent}"
        radius = "0px" if self._mode == "fullscreen" else "16px"
        card.setStyleSheet(
            f"#WarningCard {{ background-color: {bg}; border: {border};"
            f" border-radius: {radius}; }}"
        )
        outer.addWidget(card)

        v = QVBoxLayout(card)
        pad = 40 if self._mode == "fullscreen" else (18 if self._mode == "compact" else 28)
        v.setContentsMargins(pad, pad, pad, pad)
        v.setSpacing(18 if self._mode != "compact" else 10)
        if self._mode == "fullscreen":
            v.addStretch(1)

        header = QLabel(title.upper())
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(
            f"color:{accent};font-size:{header_pt}px;font-weight:800;letter-spacing:2px;"
        )
        v.addWidget(header)

        # Optional image / GIF (report §19.5)
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.hide()
        v.addWidget(self._image_label)
        self._load_image()

        body = QLabel(message or "Time to refocus.")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setStyleSheet(
            f"color:{text};font-size:{body_pt}px;font-weight:700;padding:6px 4px;"
        )
        v.addWidget(body)

        # Type-to-dismiss input (only shown in that mode)
        self._type_input = QLineEdit()
        self._type_input.setPlaceholderText("Type the message above to dismiss…")
        self._type_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._type_input.hide()
        v.addWidget(self._type_input)

        footer = QHBoxLayout()
        self._hint = QLabel("")
        self._hint.setStyleSheet(f"color:{Colors.TEXT_MUTED};font-size:12px;")
        footer.addWidget(self._hint)
        footer.addStretch(1)

        self._dismiss_btn = QPushButton("I understand")
        self._dismiss_btn.setProperty("variant", "primary")
        self._dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dismiss_btn.clicked.connect(self.dismiss)
        footer.addWidget(self._dismiss_btn)
        v.addLayout(footer)

        if self._mode == "fullscreen":
            v.addStretch(1)

    def _load_image(self) -> None:
        path = (self._config.image_path or "").strip()
        if not path or not os.path.isfile(path):
            return
        try:
            if path.lower().endswith(".gif"):
                self._movie = QMovie(path)
                self._image_label.setMovie(self._movie)
                self._movie.start()
                self._image_label.show()
            else:
                pix = QPixmap(path)
                if not pix.isNull():
                    max_w = 900 if self._mode == "fullscreen" else 420
                    max_h = 600 if self._mode == "fullscreen" else 280
                    self._image_label.setPixmap(pix.scaled(
                        max_w, max_h,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
                    self._image_label.show()
        except Exception:
            pass  # bad image must never block the warning

    # ---------------------------------------------------------------- audio
    def _setup_audio(self) -> None:
        path = (self._config.sound_path or "").strip()
        if not path or not _HAVE_AUDIO:
            return
        try:
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._audio.setVolume(max(0, min(100, self._config.volume)) / 100.0)
            self._player.setAudioOutput(self._audio)
            self._player.setSource(QUrl.fromLocalFile(path))
            if self._config.loop_sound:
                try:
                    self._player.setLoops(QMediaPlayer.Loops.Infinite)
                except Exception:
                    pass
            self._player.play()
            cap = int(self._config.sound_max_seconds or 0)
            if cap > 0:
                QTimer.singleShot(cap * 1000, self._stop_audio)
        except Exception:
            # Fail safe: show the popup regardless of audio problems.
            self._player = None
            self._audio = None

    def _stop_audio(self) -> None:
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass

    # -------------------------------------------------------------- dismiss
    def _setup_dismiss(self) -> None:
        mode = self._config.dismiss_mode or "auto_close"
        duration = max(0, int(self._config.popup_duration_seconds))
        delay = max(0, int(getattr(self._config, "close_delay_seconds", 0)))

        if mode == "type_to_dismiss":
            self._type_input.show()
            self._dismiss_btn.setText("Dismiss")
            self._type_input.textChanged.connect(self._check_typed)
            self._dismiss_btn.setEnabled(False)
            self._hint.setText("Type the message exactly to close.")
        elif mode == "hold_to_dismiss":
            self._dismiss_btn.setText("Hold to dismiss")
            self._dismiss_btn.clicked.disconnect()
            self._dismiss_btn.pressed.connect(self._hold_start)
            self._dismiss_btn.released.connect(self._hold_cancel)
            self._hint.setText("Press and hold the button to close.")
        elif mode == "click_to_close":
            self._hint.setText("Click to dismiss when you're ready.")
        else:  # auto_close
            self._dismiss_btn.setText("Dismiss now")
            self._remaining = duration
            if duration <= 0:
                QTimer.singleShot(0, self.dismiss)
            else:
                self._update_countdown()
                self._countdown = QTimer(self)
                self._countdown.setInterval(1000)
                self._countdown.timeout.connect(self._tick_countdown)
                self._countdown.start()
                QTimer.singleShot(duration * 1000, self.dismiss)

        # Delayed close button (report §9.3 / §16.2): hide the manual control
        # for the first `delay` seconds. Esc is always available as a safety.
        if delay > 0:
            self._dismiss_btn.setEnabled(False)
            self._delay_left = delay
            self._delay_timer = QTimer(self)
            self._delay_timer.setInterval(1000)
            self._delay_timer.timeout.connect(self._tick_delay)
            self._delay_timer.start()
            self._update_delay_hint()

    def _tick_delay(self) -> None:
        self._delay_left = max(0, self._delay_left - 1)
        if self._delay_left <= 0:
            self._delay_timer.stop()
            mode = self._config.dismiss_mode or "auto_close"
            # type_to_dismiss stays gated on matching text.
            if mode != "type_to_dismiss":
                self._dismiss_btn.setEnabled(True)
            self._hint.setText("")
        else:
            self._update_delay_hint()

    def _update_delay_hint(self) -> None:
        self._hint.setText(f"You can dismiss in {self._delay_left}s…")

    def _update_countdown(self) -> None:
        if not getattr(self, "_delay_left", 0):
            self._hint.setText(f"Closing in {self._remaining}s…")

    def _tick_countdown(self) -> None:
        self._remaining = max(0, self._remaining - 1)
        self._update_countdown()
        if self._remaining <= 0:
            self._countdown.stop()

    def _check_typed(self, _text: str) -> None:
        target = (self._config.message or "").strip()
        gated = getattr(self, "_delay_left", 0) > 0
        self._dismiss_btn.setEnabled(
            bool(target) and self._type_input.text().strip() == target and not gated
        )

    # hold-to-dismiss
    def _hold_start(self) -> None:
        if not self._dismiss_btn.isEnabled():
            return
        secs = max(1, int(getattr(self._config, "hold_seconds", 2)))
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self.dismiss)
        self._hold_timer.start(secs * 1000)
        self._hint.setText(f"Keep holding for {secs}s…")

    def _hold_cancel(self) -> None:
        if self._hold_timer is not None:
            self._hold_timer.stop()
            self._hold_timer = None
        if not self._closing:
            self._hint.setText("Press and hold the button to close.")

    # ---------------------------------------------------------------- close
    def dismiss(self) -> None:
        """Begin closing: fade out if configured, then close + stop audio."""
        if self._closing:
            return
        self._closing = True
        if self._config.fade_enabled and int(self._config.fade_seconds) > 0:
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(int(self._config.fade_seconds) * 1000)
            anim.setStartValue(self.windowOpacity())
            anim.setEndValue(0.0)
            anim.finished.connect(self.close)
            self._fade_anim = anim  # keep a reference
            anim.start()
        else:
            self.close()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Esc always allows escape - the popup must never trap the user (§9.5).
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._stop_audio()
        if self._movie is not None:
            try:
                self._movie.stop()
            except Exception:
                pass
        super().closeEvent(event)
        self.closed.emit()

    def present(self) -> None:
        """Show the popup positioned according to its mode."""
        if self._mode == "fullscreen":
            self.showFullScreen()
            self.raise_()
            self.activateWindow()
            return
        self.adjustSize()
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            if self._mode == "compact":
                # Top-right corner.
                x = geo.right() - self.width() - 24
                y = geo.top() + 24
            else:
                x = geo.center().x() - self.width() // 2
                y = geo.center().y() - self.height() // 2
            self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    # Backwards-compatible alias.
    def show_centered(self) -> None:
        self.present()


class WarningManager:
    """Shows warning popups one at a time and owns their lifetime."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        self._parent = parent
        self._popup: Optional[WarningPopup] = None

    def _is_showing(self) -> bool:
        return self._popup is not None and self._popup.isVisible()

    def show_warning(
        self,
        config: WarningConfig,
        message: Optional[str] = None,
        title: str = "FOCUS WARNING",
    ) -> Optional[WarningPopup]:
        """Display one warning popup. Ignored if one is already visible."""
        if self._is_showing():
            return None
        if message is None:
            message = resolve_warning_message(config)
        popup = WarningPopup(config, message, title=title, parent=self._parent)
        popup.closed.connect(self._on_closed)
        self._popup = popup
        popup.present()
        return popup

    def show_event(self, event) -> Optional[WarningPopup]:
        """Display the warning described by an engine ``WarningEvent``."""
        return self.show_warning(
            event.config,
            message=event.message,
            title=event.block_name or "FOCUS WARNING",
        )

    def test_warning(self, config: WarningConfig) -> Optional[WarningPopup]:
        """Preview a config (used by the Blocks > Warning 'Test' button).

        A preview always shows even if one is already open, so the user can
        re-test while tweaking settings.
        """
        if self._popup is not None:
            try:
                self._popup.close()
            except Exception:
                pass
            self._popup = None
        return self.show_warning(
            config,
            message=resolve_warning_message(config),
            title="TEST WARNING",
        )

    def _on_closed(self) -> None:
        self._popup = None
