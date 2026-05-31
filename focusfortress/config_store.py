"""Thread-safe JSON config + stats persistence."""
from __future__ import annotations

import contextlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .models import AppConfig, BlockList, GlobalSettings
from .paths import CONFIG_FILE, STATS_FILE, STATE_FILE, ensure_data_dirs


_lock = threading.RLock()


# ---- Cross-process lock for state.json -------------------------------------
#
# state.json is read-modify-written by up to four separate processes (the main
# engine, the normal watchdog, and both force-protect watchdogs). The
# per-process RLock (`_lock`) only serialises threads *within* one process, so
# without an inter-process lock a save built on a slightly-stale read can clobber
# keys another process wrote concurrently (e.g. the engine's cooldown/clock
# state). `_state_cross_process_lock()` provides that coordination via a Windows
# named mutex. It is fail-soft by design: on non-Windows, or if anything goes
# wrong creating/acquiring the mutex, it degrades to a plain no-op (the
# in-process RLock still applies) so the cross-platform test suite keeps passing.

@contextlib.contextmanager
def _state_cross_process_lock(timeout_ms: int = 5000):
    """Best-effort cross-process mutex around state.json writes.

    On Windows acquires a named mutex (``Local\\FocusFortress_state_mutex``).
    On any failure or on non-Windows platforms this is a no-op and callers rely
    on the in-process RLock. Never raises.
    """
    handle = None
    kernel32 = None
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            # "Local\\" namespace works without elevation; a "Global\\" mutex
            # would be ideal for cross-session coordination but can be denied,
            # so we use the always-available Local namespace.
            name = "Local\\FocusFortress_state_mutex"
            handle = kernel32.CreateMutexW(None, False, name)
            if handle:
                # WaitForSingleObject returns regardless of whether we actually
                # got ownership; either way we proceed after the timeout so a
                # stuck holder can never hang us indefinitely.
                kernel32.WaitForSingleObject(handle, int(timeout_ms))
            else:
                kernel32 = None  # nothing to release/close
        except Exception:
            handle = None
            kernel32 = None
    try:
        yield
    finally:
        if handle and kernel32 is not None:
            try:
                kernel32.ReleaseMutex(handle)
            except Exception:
                pass
            try:
                kernel32.CloseHandle(handle)
            except Exception:
                pass


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
        with _state_cross_process_lock():
            ensure_data_dirs()
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
            tmp.replace(STATE_FILE)


def update_state(mutator: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """Atomically load, mutate and save state under both locks.

    Performs a locked read-modify-write so callers don't race on the unguarded
    ``load_state(); state[...] = ...; save_state(state)`` sequence across
    processes. ``mutator`` is called with the current state dict; it may mutate
    it in place (returning ``None``) or return a replacement dict. The whole
    cycle runs under the in-process RLock *and* the cross-process mutex, so the
    read the save is built on cannot be stale relative to another writer.

    Returns the state dict that was saved.
    """
    with _lock:
        with _state_cross_process_lock():
            state = load_state()
            result = mutator(state)
            if result is not None:
                state = result
            save_state(state)
            return state
