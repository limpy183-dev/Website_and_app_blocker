"""Warning presets and message helpers.

This module is pure data/logic (no Qt, no audio) so it can be imported and
unit-tested anywhere.  It owns:

* ``WARNING_PRESETS`` - ready-made warning profiles (report §14).
* ``apply_warning_preset`` - fill a :class:`~focusfortress.models.WarningConfig`
  from a preset while leaving every field editable afterwards.
* ``resolve_warning_message`` - pick the message to show, supporting the
  optional random-message pool (report §15) with a fallback to the single
  ``message`` field.
"""
from __future__ import annotations

import random
from typing import Dict, Optional

from .models import WarningConfig


# ---------------------------------------------------------------------------
# Presets (report §14) - sensible starting points the user can then tweak.
# Each preset is a plain dict of WarningConfig field overrides.
# ---------------------------------------------------------------------------
WARNING_PRESETS: Dict[str, Dict[str, object]] = {
    "calm_reminder": {
        "theme": "calm",
        "builtin_sound": "chime",
        "message": "Gentle reminder: time to step away.",
        "messages": [
            "Gentle reminder: time to step away.",
            "Take a breath. Back to what matters.",
        ],
        "volume": 50,
        "popup_duration_seconds": 8,
        "fade_enabled": True,
        "fade_seconds": 2,
        "dismiss_mode": "auto_close",
    },
    "red_alert": {
        "theme": "red_alert",
        "builtin_sound": "alarm",
        "popup_mode": "centered",
        "message": "Time is up. Get back on task.",
        "messages": [
            "Time is up. Get back on task.",
            "STOP. You said you'd focus.",
            "LOCK IN.",
        ],
        "volume": 90,
        "popup_duration_seconds": 10,
        "fade_enabled": True,
        "fade_seconds": 2,
        "dismiss_mode": "click_to_close",
    },
    "study_mode": {
        "theme": "exam",
        "builtin_sound": "chime",
        "message": "Focus time. Distractions are blocked.",
        "messages": [
            "Focus time. Distractions are blocked.",
            "Eyes on the work.",
        ],
        "volume": 70,
        "popup_duration_seconds": 8,
        "dismiss_mode": "auto_close",
    },
    "sleep_reminder": {
        "theme": "calm",
        "builtin_sound": "chime",
        "message": "It's late. Wind down and head to bed.",
        "messages": [
            "It's late. Wind down and head to bed.",
            "Screens off. Sleep matters.",
        ],
        "volume": 40,
        "popup_duration_seconds": 12,
        "fade_enabled": True,
        "fade_seconds": 3,
        "dismiss_mode": "auto_close",
    },
    "gaming_limit": {
        "theme": "red_alert",
        "builtin_sound": "alarm",
        "message": "Time is up. Close the game and go revise.",
        "messages": [
            "Time is up. Close the game and go revise.",
            "Game over for now. Back to work.",
        ],
        "volume": 85,
        "popup_duration_seconds": 10,
        "dismiss_mode": "click_to_close",
    },
    "exam_panic": {
        "theme": "exam",
        "builtin_sound": "siren",
        "message": "PHYSICS PAPER 2 IS NOT REVISING ITSELF.",
        "messages": [
            "PHYSICS PAPER 2 IS NOT REVISING ITSELF.",
            "GET OFF YOUTUBE. GO REVISE.",
            "YOU SAID 30 MINUTES.",
        ],
        "volume": 100,
        "popup_duration_seconds": 12,
        "dismiss_mode": "click_to_close",
    },
}


def apply_warning_preset(
    cfg: WarningConfig,
    preset_name: str,
    *,
    sounds: Optional[Dict[str, str]] = None,
) -> WarningConfig:
    """Populate ``cfg`` from a named preset, enabling the warning.

    The preset fills in the fields it defines; everything else keeps its
    current value.  The config stays fully editable afterwards (the caller can
    append to ``cfg.messages``, change the message, etc.).

    ``sounds`` is an optional ``{name: path}`` map of built-in sounds (from
    :func:`focusfortress.sounds.ensure_builtin_sounds`).  When provided, a
    preset's ``builtin_sound`` is resolved to a real path and stored in
    ``cfg.sound_path``.  It is left out by default so applying a preset never
    touches the filesystem.

    Raises ``KeyError`` if ``preset_name`` is unknown.
    """
    preset = WARNING_PRESETS[preset_name]
    cfg.enabled = True
    cfg.theme = str(preset.get("theme", preset_name))
    for key, value in preset.items():
        if key in ("theme", "builtin_sound"):
            continue
        if key == "messages":
            # Use a fresh, mutable copy so callers can append safely.
            cfg.messages = list(value)  # type: ignore[arg-type]
        elif hasattr(cfg, key):
            setattr(cfg, key, value)
    builtin = preset.get("builtin_sound")
    if builtin and sounds and sounds.get(builtin):
        cfg.sound_path = sounds[builtin]
    return cfg


def resolve_warning_message(cfg: WarningConfig) -> str:
    """Return the message to display for this warning.

    If a non-empty random pool (``messages``) is configured, one line is
    chosen at random; otherwise the single ``message`` field is used.
    """
    pool = [m for m in (getattr(cfg, "messages", None) or []) if str(m).strip()]
    if pool:
        return random.choice(pool)
    return cfg.message
