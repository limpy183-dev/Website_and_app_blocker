"""Thread-safe JSON config + stats persistence."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict

from .models import AppConfig, BlockList, GlobalSettings
from .paths import CONFIG_FILE, STATS_FILE, STATE_FILE, ensure_data_dirs


_lock = threading.RLock()


DEFAULT_DISTRACTIONS = [
    "facebook.com", "instagram.com", "tiktok.com", "twitter.com", "x.com",
    "reddit.com", "youtube.com", "netflix.com", "9gag.com", "twitch.tv",
    "imgur.com", "pinterest.com", "snapchat.com",
]


def _default_config() -> AppConfig:
    cfg = AppConfig()
    cfg.blocks.append(
        BlockList(name="Distractions", sites=list(DEFAULT_DISTRACTIONS))
    )
    cfg.blocks.append(BlockList(name="Work focus", sites=[]))
    cfg.settings = GlobalSettings()
    return cfg


def load_config() -> AppConfig:
    with _lock:
        ensure_data_dirs()
        if not CONFIG_FILE.exists():
            cfg = _default_config()
            save_config(cfg)
            return cfg
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return AppConfig.from_dict(data)
        except Exception:
            # Corrupt - back up and regenerate.
            backup = CONFIG_FILE.with_suffix(".corrupt.json")
            try:
                CONFIG_FILE.replace(backup)
            except Exception:
                pass
            cfg = _default_config()
            save_config(cfg)
            return cfg


def save_config(cfg: AppConfig) -> None:
    with _lock:
        ensure_data_dirs()
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(CONFIG_FILE)


# ---- Stats ----

def load_stats() -> Dict[str, Any]:
    with _lock:
        if not STATS_FILE.exists():
            return {"sites": {}, "apps": {}, "days": {}}
        try:
            return json.loads(STATS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"sites": {}, "apps": {}, "days": {}}


def save_stats(stats: Dict[str, Any]) -> None:
    with _lock:
        ensure_data_dirs()
        tmp = STATS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(stats, indent=2), encoding="utf-8")
        tmp.replace(STATS_FILE)


def clear_stats() -> None:
    with _lock:
        save_stats({"sites": {}, "apps": {}, "days": {}})


# ---- Runtime state (active locks etc.) ----

def load_state() -> Dict[str, Any]:
    with _lock:
        if not STATE_FILE.exists():
            return {}
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}


def save_state(state: Dict[str, Any]) -> None:
    with _lock:
        ensure_data_dirs()
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
