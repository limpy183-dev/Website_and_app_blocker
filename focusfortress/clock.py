"""Monotonic-time facade.

When ``ignore_time_changes`` is enabled in settings, all scheduling and timer
evaluation uses ``time.monotonic()`` offsets captured against a wall-clock
baseline stored persistently. That means:

* Changing the Windows clock cannot shorten a timer lock.
* Setting the clock forward/back does not make a schedule window "skip".
* Rebooting is still detectable (boot_time) so restart-locks still work.

If the setting is disabled, ``wall_now()`` is just ``datetime.now()``.

Persistence across restarts
---------------------------
``time.monotonic()`` is per-boot and cannot be persisted, so on its own a
restart would freeze the protected clock at the value it had when the baseline
was last captured. To avoid that, ``_persist()`` records BOTH the wall baseline
(``wall_ref``) and the real system clock at the moment of persisting
(``saved_at``). On startup ``_load_baseline()`` advances ``wall_ref`` forward by
the real wall time that elapsed *while the process was off* (``now - saved_at``).

That delta is clamped to reject tampering / nonsense: a negative delta (the
system clock moved backward while we were off) is treated as 0, and an absurdly
large delta is capped (see ``_MAX_OFFLINE_DELTA``). The design intent is that
schedules SHOULD track real wall time across restarts, so the cap is generous;
its only job is to swallow obviously-bogus jumps. While the process is RUNNING,
``time.monotonic()`` still governs, so clock moves during runtime are ignored --
which is the whole point of the feature.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Optional

from .config_store import load_state, save_state

_lock = threading.RLock()
_enabled = False

# In-process cache; mirrored to state file for persistence across restarts.
_mono_ref: Optional[float] = None      # time.monotonic() at baseline capture
_wall_ref: Optional[dt.datetime] = None  # protected-clock value at baseline capture

# Generous cap on how far the protected clock may jump forward to account for
# time the process spent off. Real reboots/shutdowns can legitimately be days,
# but anything past this is almost certainly a tampered/garbage timestamp.
_MAX_OFFLINE_DELTA = 400 * 24 * 60 * 60  # 400 days, in seconds


def _load_baseline() -> None:
    """Restore the baseline on startup, advancing it for offline wall time.

    ``_mono_ref`` is re-captured from this boot's ``time.monotonic()`` (it can't
    persist). ``_wall_ref`` is restored from disk and then advanced by the real
    wall time that passed while the process was OFF -- i.e. between the last
    ``saved_at`` and ``datetime.now()`` -- so the protected clock resumes near
    real "now" instead of freezing at the last-persisted value. That delta is
    clamped to [0, _MAX_OFFLINE_DELTA] to reject tampering / nonsense.
    """
    global _mono_ref, _wall_ref
    state = load_state()
    clk = state.get("monotonic_clock") or {}

    try:
        _wall_ref = dt.datetime.fromisoformat(clk["wall_ref"])
    except Exception:
        _wall_ref = None

    saved_at: Optional[dt.datetime] = None
    try:
        saved_at = dt.datetime.fromisoformat(clk["saved_at"])
    except Exception:
        saved_at = None

    # Monotonic is per-boot and cannot be persisted; always re-capture.
    _mono_ref = time.monotonic()

    if _wall_ref is None:
        # First ever run: trust the current clock as the baseline.
        _wall_ref = dt.datetime.now()
        _persist()
        return

    # Advance the baseline by the real wall time spent off (now - saved_at).
    # If saved_at is missing/unparseable, don't advance (delta = 0) rather than
    # guess -- never crash here.
    delta = 0.0
    if saved_at is not None:
        try:
            delta = (dt.datetime.now() - saved_at).total_seconds()
        except Exception:
            delta = 0.0
    # Clamp: negative means the clock moved backward while we were off -> ignore.
    # Cap the upper end to swallow obviously-tampered timestamps.
    if delta < 0:
        delta = 0.0
    elif delta > _MAX_OFFLINE_DELTA:
        delta = _MAX_OFFLINE_DELTA
    _wall_ref = _wall_ref + dt.timedelta(seconds=delta)

    # Re-persist so wall_ref/saved_at reflect this startup going forward.
    _persist()


def _persist() -> None:
    state = load_state()
    state["monotonic_clock"] = {
        "wall_ref": (_wall_ref or dt.datetime.now()).isoformat(timespec="seconds"),
        # saved_at is the REAL system clock at persist time -- persistence
        # bookkeeping, not timer logic, so datetime.now() is intentional here.
        "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    save_state(state)


def configure(enabled: bool) -> None:
    """Enable/disable monotonic-time mode."""
    global _enabled
    with _lock:
        _enabled = bool(enabled)
        if _enabled and _mono_ref is None:
            _load_baseline()


def reanchor() -> None:
    """Reset the baseline to right now. Call this whenever you *trust* the
    current wall clock (e.g. just-enabled a block, first run after install)."""
    global _mono_ref, _wall_ref
    with _lock:
        _mono_ref = time.monotonic()
        _wall_ref = dt.datetime.now()
        _persist()


def wall_now() -> dt.datetime:
    """Return 'now' - monotonic-derived if protection is on, real wall otherwise."""
    if not _enabled:
        return dt.datetime.now()
    with _lock:
        if _mono_ref is None or _wall_ref is None:
            _load_baseline()
        elapsed = time.monotonic() - _mono_ref  # type: ignore[arg-type]
        return _wall_ref + dt.timedelta(seconds=elapsed)  # type: ignore[operator]


def boot_time() -> dt.datetime:
    """Wrapper so callers don't need to import psutil everywhere."""
    import psutil
    return dt.datetime.fromtimestamp(psutil.boot_time())


# Initialise lazily on import so callers always have something usable.
_load_baseline()
