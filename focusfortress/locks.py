"""Lock-method evaluation. Returns (allowed_to_disable, reason_if_not)."""
from __future__ import annotations

import datetime as dt
from typing import Tuple

from .clock import boot_time, wall_now
from .models import BlockList, LockConfig
from .security import verify_password


def _time_in_range(now: dt.time, start: dt.time, end: dt.time) -> bool:
    if start <= end:
        return start <= now <= end
    # overnight window
    return now >= start or now <= end


def can_disable(block: BlockList,
                *,
                password_attempt: str | None = None,
                random_attempt: str | None = None,
                random_expected: str | None = None,
                ) -> Tuple[bool, str]:
    lock = block.lock
    kind = lock.kind or "none"
    now = wall_now()

    if kind == "none":
        return True, ""

    if kind == "timer":
        if not lock.until:
            return True, ""
        try:
            until = dt.datetime.fromisoformat(lock.until)
        except ValueError:
            return True, ""
        if now >= until:
            return True, ""
        remaining = until - now
        return False, f"Timer lock active. {remaining} remaining until {until:%Y-%m-%d %H:%M}."

    if kind == "random":
        if random_attempt is None or random_expected is None:
            return False, f"Type the {lock.random_length}-character unlock string to disable."
        if random_attempt == random_expected:
            return True, ""
        return False, "Unlock string did not match. Try again."

    if kind == "range":
        try:
            s = dt.time.fromisoformat(lock.range_start)
            e = dt.time.fromisoformat(lock.range_end)
        except ValueError:
            return True, ""
        in_range = _time_in_range(now.time().replace(microsecond=0), s, e)
        if lock.range_mode == "allow_during":
            # Changes only allowed during the range.
            if in_range:
                return True, ""
            return False, f"Changes only allowed between {lock.range_start} and {lock.range_end}."
        # block_during: changes NOT allowed during the range.
        if in_range:
            return False, f"Locked between {lock.range_start} and {lock.range_end}."
        return True, ""

    if kind == "restart":
        # Allowed only if the system booted AFTER the lock was armed.
        if not block.active_since:
            return True, ""
        try:
            armed = dt.datetime.fromisoformat(block.active_since)
        except ValueError:
            return True, ""
        if boot_time() >= armed:
            return True, ""
        return False, "Restart the computer to unlock this block."

    if kind == "password":
        if password_attempt is None:
            return False, "Password required to disable this block."
        if lock.password_hash and lock.password_salt and verify_password(
            password_attempt, lock.password_hash, lock.password_salt
        ):
            return True, ""
        return False, "Incorrect password."

    return True, ""


def describe_lock(lock: LockConfig) -> str:
    if lock.kind == "none" or not lock.kind:
        return "No lock"
    if lock.kind == "timer":
        return f"Timer until {lock.until or '-'}"
    if lock.kind == "random":
        return f"Random text ({lock.random_length} chars)"
    if lock.kind == "range":
        word = "blocked" if lock.range_mode == "block_during" else "allowed"
        return f"Time range ({word} {lock.range_start}-{lock.range_end})"
    if lock.kind == "restart":
        return "Restart required"
    if lock.kind == "password":
        return "Password"
    return lock.kind
