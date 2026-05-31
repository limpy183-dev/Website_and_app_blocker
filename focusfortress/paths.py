"""Centralised filesystem paths for FocusFortress."""
from __future__ import annotations

import os
from pathlib import Path


def _programdata() -> Path:
    # %PROGRAMDATA% is writable by admins; normal users can only read.
    # That is exactly what we want for a block list.
    base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    return Path(base) / "FocusFortress"


DATA_DIR: Path = _programdata()
CONFIG_FILE: Path = DATA_DIR / "config.json"
STATS_FILE: Path = DATA_DIR / "stats.json"
STATE_FILE: Path = DATA_DIR / "state.json"          # runtime: active locks, allowances, etc.
BLOCKPAGE_DIR: Path = DATA_DIR / "blockpage"
LOG_FILE: Path = DATA_DIR / "focusfortress.log"

HOSTS_FILE: Path = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"

HOSTS_MARK_BEGIN = "# >>> FocusFortress begin >>>"
HOSTS_MARK_END = "# <<< FocusFortress end <<<"


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BLOCKPAGE_DIR.mkdir(parents=True, exist_ok=True)
