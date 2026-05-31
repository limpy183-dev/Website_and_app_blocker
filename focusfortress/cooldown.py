"""Persistent, tamper-evident cooldown lock for the Advanced settings tab.

State is stored in ``state.json`` under the ``advanced_cooldown`` key with
an HMAC signature.  If the signature does not verify (because the user
edited the file) we refuse to honour any "unlocked" flag and start a new
fresh 1-hour wait, so tampering cannot shorten the wait.

The signing key lives in ``%PROGRAMDATA%\\FocusFortress\\.cooldown.key`` and
is locked down with a real Windows ACL (SYSTEM + Administrators only) so a
non-admin user cannot read it and forge a signature.  This is
defense-in-depth: a determined *local administrator* can always take
ownership of (or simply delete) the key, which only forces a fresh
cooldown rather than granting an instant unlock.

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
import subprocess
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


def _restrict_key_acl(path) -> None:
    """Lock the HMAC key file down to SYSTEM + Administrators only.

    %PROGRAMDATA%\\FocusFortress is user-READABLE by design, so without a
    real ACL a non-admin user could read the signing key, forge a valid
    signature, and write a forged "unlocked" state.  We use icacls with the
    well-known SIDs (``*S-1-5-18`` = LocalSystem, ``*S-1-5-32-544`` =
    Administrators) so it is language-independent.

    This is defense-in-depth only: a determined *local administrator* can
    always take ownership / remove the ACL (or delete the key entirely),
    which simply forces a fresh cooldown.  The goal is to keep a normal
    (non-admin) user from reading the key.

    Fail-soft: a no-op on non-Windows and best-effort if icacls fails.
    """
    if os.name != "nt":
        return
    try:
        p = str(path)
        # Remove inherited perms, then grant only SYSTEM + Administrators full control.
        subprocess.run(
            ["icacls", p, "/inheritance:r"],
            capture_output=True,
            creationflags=0x08000000,
        )
        subprocess.run(
            ["icacls", p, "/grant:r", "*S-1-5-18:F", "*S-1-5-32-544:F"],
            capture_output=True,
            creationflags=0x08000000,
        )
    except Exception as e:
        log.debug("cooldown key ACL failed: %s", e)


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
            _restrict_key_acl(_KEY_FILE)
        except Exception:
            pass
    except Exception as e:
        log.debug("cooldown key write failed: %s", e)
    return new


def _boot_id() -> str:
    """Identifier for the current boot session, used to bind monotonic
    deadlines to this boot.  ``time.monotonic()`` resets on reboot, so a
    stale ``until_mono`` from a previous boot can coincidentally fall inside
    the acceptance window and be wrongly trusted.  Tagging the payload with
    the boot time lets ``remaining_seconds()`` reject cross-boot monotonic
    values.  Fail-soft: returns ``""`` if psutil is unavailable.
    """
    try:
        import psutil
        return f"{psutil.boot_time():.0f}"
    except Exception:
        return ""


def _sign(payload: dict) -> str:
    msg = "|".join(
        f"{k}={payload.get(k, '')}"
        for k in ("until_wall", "until_mono", "unlocked", "started_wall", "boot")
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
        # Only trust the monotonic deadline if it was recorded during the
        # current boot session.  time.monotonic() resets on reboot, so a
        # stale "until_mono" from a previous boot can coincidentally land in
        # the acceptance window below and be wrongly trusted - bind it to the
        # boot id so cross-boot monotonic values are rejected (we then rely on
        # the wall deadline, which survives reboot).
        trust_mono = True
        stored_boot = payload.get("boot", "")
        if stored_boot:
            try:
                import psutil
                cur_boot = int(float(psutil.boot_time()))
                if cur_boot != int(float(stored_boot)):
                    trust_mono = False  # rebooted since the cooldown was stored
            except Exception:
                pass  # psutil unavailable -> fall back to current behavior

        if trust_mono:
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
        "boot": _boot_id(),
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
        "boot": _boot_id(),
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
