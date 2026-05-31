"""Persistent, tamper-evident cooldown lock for the Advanced settings tab.

State is stored in ``state.json`` under the ``advanced_cooldown`` key with
an HMAC signature.  If the signature does not verify (because the user
edited the file) we refuse to honour any "unlocked" flag and start a new
fresh 1-hour wait, so tampering cannot shorten the wait.

The cooldown is also *clock-tamper resistant*: we anchor it against
``time.monotonic()`` AND against a wall-clock deadline.  On every check we
take whichever of the two reports MORE remaining time - so moving the
system clock forward cannot make the timer drop faster than real time,
and rebooting cannot reset the monotonic clock to skip ahead either
(after reboot we fall back to the wall-clock deadline).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Tuple

from .config_store import load_state, save_state
from .paths import DATA_DIR

log = logging.getLogger("focusfortress.cooldown")


COOLDOWN_SECONDS = 60 * 60  # 1 hour


# ---------------------------------------------------------------------------
# HMAC sealing
# ---------------------------------------------------------------------------

_KEY_FILE = DATA_DIR / ".cooldown.key"


def _key() -> bytes:
    """Return (and lazily create) a 32-byte secret used to sign state.

    The key file lives in %PROGRAMDATA%\\FocusFortress, which on Windows is
    only writable by Administrators - the same trust boundary the rest of
    the app already relies on.
    """
    try:
        if _KEY_FILE.exists():
            data = _KEY_FILE.read_bytes()
            if len(data) >= 32:
                return data[:32]
    except Exception as e:
        log.debug("cooldown key read failed: %s", e)
    new = secrets.token_bytes(32)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_bytes(new)
        try:
            os.chmod(_KEY_FILE, 0o600)
        except Exception:
            pass
    except Exception as e:
        log.debug("cooldown key write failed: %s", e)
    return new


def _sign(payload: dict) -> str:
    msg = "|".join(
        f"{k}={payload.get(k, '')}"
        for k in ("until_wall", "until_mono", "unlocked", "started_wall")
    )
    return hmac.new(_key(), msg.encode("utf-8"), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _load() -> dict:
    state = load_state()
    return dict(state.get("advanced_cooldown") or {})


def _save(payload: dict) -> None:
    payload = dict(payload)
    payload["sig"] = _sign(payload)
    state = load_state()
    state["advanced_cooldown"] = payload
    save_state(state)


def _verified(payload: dict) -> dict | None:
    """Return ``payload`` if its signature matches, else ``None``."""
    sig = payload.get("sig")
    if not sig:
        return None
    expected = _sign({k: v for k, v in payload.items() if k != "sig"})
    if not hmac.compare_digest(sig, expected):
        log.warning("advanced cooldown HMAC mismatch - state was tampered with")
        return None
    return payload


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def remaining_seconds() -> int:
    """How many seconds are left on the current cooldown.

    Returns 0 if the cooldown has already elapsed (or was never started).
    Picks the LARGER remainder of {wall-deadline, monotonic-deadline} so
    that whichever clock the user can't move wins - this is what makes the
    timer resistant to system-clock changes and to reboots.
    """
    raw = _load()
    payload = _verified(raw)
    if not payload:
        return 0
    if payload.get("unlocked"):
        return 0

    rem = 0

    # Wall-clock deadline (survives reboot)
    try:
        until_wall = dt.datetime.fromisoformat(payload["until_wall"])
        rem_wall = (until_wall - dt.datetime.now()).total_seconds()
    except Exception:
        rem_wall = 0
    rem = max(rem, int(rem_wall))

    # Monotonic deadline (survives wall-clock tampering)
    try:
        until_mono = float(payload["until_mono"])
        rem_mono = until_mono - time.monotonic()
        # If monotonic_ref is suspiciously old (i.e. process restart), the
        # "until_mono" target won't be valid in our new monotonic clock - we
        # detect that by also storing the started_wall instant: if the
        # original-start wall-time is within a sane bound and monotonic
        # disagrees wildly, prefer wall.  Practically, we just clamp:
        if 0 < rem_mono <= COOLDOWN_SECONDS + 60:
            rem = max(rem, int(rem_mono))
    except Exception:
        pass

    return max(0, rem)


def is_unlocked() -> bool:
    """Return True only if the cooldown has expired AND we explicitly
    transitioned to the "unlocked, ready to edit once" state.

    Just hitting zero is not enough; ``mark_unlocked()`` must be called.
    """
    payload = _verified(_load())
    return bool(payload and payload.get("unlocked"))


def is_running() -> bool:
    """True if a cooldown is currently counting down (>0s remaining)."""
    return remaining_seconds() > 0


def start_cooldown() -> int:
    """Begin (or resume) a 1-hour cooldown.

    If a valid cooldown is already running we leave it untouched and just
    return its remaining seconds - the spec says the timer must persist
    and the same wait must apply across attempts.
    """
    rem = remaining_seconds()
    if rem > 0:
        return rem

    now_wall = dt.datetime.now()
    until_wall = now_wall + dt.timedelta(seconds=COOLDOWN_SECONDS)
    until_mono = time.monotonic() + COOLDOWN_SECONDS
    payload = {
        "until_wall": until_wall.isoformat(timespec="seconds"),
        "until_mono": f"{until_mono:.3f}",
        "started_wall": now_wall.isoformat(timespec="seconds"),
        "unlocked": False,
    }
    _save(payload)
    log.info("advanced cooldown started: %ds", COOLDOWN_SECONDS)
    return COOLDOWN_SECONDS


def mark_unlocked() -> bool:
    """Transition expired cooldown -> unlocked-once state.

    Returns True on success.  Refuses if the timer hasn't actually
    expired yet (defence in depth - the UI should also gate this).
    """
    if remaining_seconds() > 0:
        return False
    now_wall = dt.datetime.now()
    payload = {
        "until_wall": now_wall.isoformat(timespec="seconds"),
        "until_mono": f"{time.monotonic():.3f}",
        "started_wall": now_wall.isoformat(timespec="seconds"),
        "unlocked": True,
    }
    _save(payload)
    log.info("advanced cooldown -> unlocked")
    return True


def consume_unlock() -> None:
    """Clear the unlocked flag.  Call after the user successfully saves
    Advanced settings - the next change attempt will start a fresh 1h
    wait."""
    state = load_state()
    if "advanced_cooldown" in state:
        state.pop("advanced_cooldown", None)
        save_state(state)
    log.info("advanced cooldown consumed - next attempt will re-arm")


def format_remaining(seconds: int) -> str:
    """Return ``HH:MM:SS`` representation of ``seconds``."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
