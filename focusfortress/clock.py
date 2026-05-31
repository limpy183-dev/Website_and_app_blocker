"""Monotonic-time facade.

When ``ignore_time_changes`` is enabled in settings, all scheduling and timer
evaluation uses ``time.monotonic()`` offsets captured against a wall-clock
baseline stored persistently. That means:

* Changing the Windows clock cannot shorten a timer lock.
* Setting the clock forward/back does not make a schedule window "skip".
* Rebooting is still detectable (boot_time) so restart-locks still work.

If the setting is disabled, ``wall_now()`` is just ``datetime.now()``.
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
_wall_ref: Optional[dt.datetime] = None  # datetime.now() at baseline capture


def _load_baseline() -> None:
    global _mono_ref, _wall_ref
    state = load_state()
    clk = state.get("monotonic_clock") or {}
    try:
        _wall_ref = dt.datetime.fromisoformat(clk["wall_ref"])
    except Exception:
        _wall_ref = None
    # We can't persist monotonic_ref across process restarts (it's per-boot),
    # so on startup we recompute: assume "now" is correct at first-start and
    # re-anchor. If the clock was moved while we were off, the NEXT lock start
    # will re-anchor. This is acceptable - it only means the very first boot
    # after install can't catch pre-install tampering.
    _mono_ref = time.monotonic()
    if _wall_ref is None:
        _wall_ref = dt.datetime.now()
        _persist()


def _persist() -> None:
    state = load_state()
    state["monotonic_clock"] = {
        "wall_ref": (_wall_ref or dt.datetime.now()).isoformat(timespec="seconds"),
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
