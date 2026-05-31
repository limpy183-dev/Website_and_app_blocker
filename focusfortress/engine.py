"""Core orchestrator: decides which blocks are currently active and enforces them."""
from __future__ import annotations

import datetime as dt
import getpass
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from . import clock
from . import force_protect
from . import selfprotect
from . import watchdog as _watchdog
from .advanced import set_task_manager_blocked, set_time_change_blocked
from .blocking.apps import AppBlocker
from .blocking.doh import resolve_blocklist as doh_block_list
from .blocking.hosts import clear_block_section, flush_dns, write_block_section
from .blocking.proxy import BlockingProxy
from .blocking.winproxy import _DEFAULT_BYPASS, disable_proxy, enable_proxy, read_proxy
from .config_store import load_config, load_state, save_config, save_state
from .idle import idle_seconds
from .locks import can_disable
from .models import AppConfig, BlockList, ScheduleSlot, WarningConfig
from .warnings import resolve_warning_message

log = logging.getLogger("focusfortress.engine")


class LockedError(Exception):
    """Raised when a block cannot be disabled because its lock denies it."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class WarningEvent:
    block_name: str
    message: str
    config: WarningConfig


def _current_user() -> str:
    try:
        return getpass.getuser().lower()
    except Exception:
        return ""


def _now() -> dt.datetime:
    return clock.wall_now()


def _format_remaining(delta: dt.timedelta) -> str:
    """Format a positive timedelta as a short string like '1h 22m' or '45m'."""
    secs = max(0, int(delta.total_seconds()))
    h, rem = divmod(secs, 3600)
    m, _ = divmod(rem, 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def _slot_active_now(slot: ScheduleSlot, now: dt.datetime) -> bool:
    if slot.day != now.weekday():
        return False
    try:
        s = dt.time.fromisoformat(slot.start)
        e = dt.time.fromisoformat(slot.end)
    except ValueError:
        return False
    t = now.time()
    if s <= e:
        return s <= t <= e
    return t >= s or t <= e


class Engine:
    """Singleton-ish orchestrator."""
    _instance: Optional["Engine"] = None

    def __init__(self) -> None:
        self.config: AppConfig = load_config()
        self._proxy = BlockingProxy(port=self.config.settings.proxy_port)
        self._apps = AppBlocker(poll_seconds=1.0)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Guards config mutation/save across the engine thread and CLI/UI callers.
        self._state_lock = threading.RLock()
        # Cache of allowance consumption tick (monotonic: immune to clock moves).
        self._last_allowance_tick = time.monotonic()
        # Frozen Turkey: only fire the action on window ENTRY, not every tick.
        self._frozen_turkey_actioned = False
        # Pre-action countdown state (report §2.7).
        self._frozen_pending_deadline: Optional[float] = None  # monotonic
        self._frozen_cancelled_window = False
        self._frozen_action_handler: Optional[Callable[[str, int], None]] = None
        # Pomodoro state
        self._pomo_phase: str = "idle"    # idle|work|break|long_break
        self._pomo_phase_until: Optional[dt.datetime] = None
        self._pomo_cycle: int = 0
        self._pomo_paused_remaining: Optional[float] = None  # seconds left when paused
        # ---- Warning subsystem state ----
        # Several entry points drive warnings (see the warning section below);
        # each keeps its own "what was active last pass" set so they don't
        # interfere with one another.
        self._active_block_names: set[str] = set()        # _apply() dispatch
        self._last_warning_at: Dict[str, float] = {}      # for repeat throttling
        self._locked_block_names: set[str] = set()        # timer-lock expiry tracking
        self._active_warning_blocks: set[str] = set()     # _emit_block_activation_warnings
        self._previous_active_block_keys: set = set()     # _emit_newly_active_warnings
        self._warning_listeners: List[Callable] = []      # add_warning_listener (event)
        self._warning_handler: Optional[Callable[[WarningEvent], None]] = None
        self._warning_callback: Optional[Callable[[BlockList, str], None]] = None
        self._pending_warning_events: List[WarningEvent] = []

    # ---------- singleton ----------

    @classmethod
    def instance(cls) -> "Engine":
        if cls._instance is None:
            cls._instance = Engine()
        return cls._instance

    # ---------- public API ----------

    def _lock(self) -> threading.RLock:
        """Return the reentrant state lock, creating it lazily.

        Some tests build the engine via ``Engine.__new__`` (bypassing
        ``__init__``); creating the lock on first use keeps those paths working
        without requiring full construction.
        """
        lock = getattr(self, "_state_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._state_lock = lock
        return lock

    def reload_config(self) -> None:
        self.config = load_config()

    def save(self) -> None:
        with self._lock():
            save_config(self.config)

    def add_warning_listener(self, listener: Callable) -> None:
        """Register a warning listener.

        Listeners registered here are invoked with a single
        :class:`WarningEvent` from the normal ``_apply()`` path (this is what
        the UI uses).  The direct ``_emit_block_activation_warnings`` helper
        invokes them as ``listener(block_name, warning_config)`` instead.
        """
        if listener not in self._warning_listeners:
            self._warning_listeners.append(listener)

    def remove_warning_listener(self, listener: Callable) -> None:
        if listener in self._warning_listeners:
            self._warning_listeners.remove(listener)

    def set_warning_handler(self, handler: Optional[Callable[[WarningEvent], None]]) -> None:
        """Set the single handler invoked with a :class:`WarningEvent`.

        Any events that were emitted while no handler was registered are
        flushed to ``handler`` immediately (so warnings are never lost if the
        engine ticks before the UI has wired itself up).
        """
        self._warning_handler = handler
        pending = getattr(self, "_pending_warning_events", None)
        if handler is not None and pending:
            self._pending_warning_events = []
            for event in pending:
                try:
                    handler(event)
                except Exception:
                    log.exception("warning handler failed")

    def set_warning_callback(self, callback: Optional[Callable[[BlockList, str], None]]) -> None:
        """Set a ``callback(block, reason)`` invoked when a block's warning fires."""
        self._warning_callback = callback

    def find_block(self, name: str) -> Optional[BlockList]:
        for b in self.config.blocks:
            if b.name.lower() == name.lower():
                return b
        return None

    def set_block_enabled(
        self,
        name: str,
        enabled: bool,
        *,
        password_attempt=None,
        random_attempt=None,
        random_expected=None,
    ) -> bool:
        with self._lock():
            b = self.find_block(name)
            if not b:
                return False
            # Centralized lock enforcement: disabling an active, locked block
            # must pass the lock's can_disable() gate.
            if (not enabled) and b.enabled and (b.lock.kind or "none") != "none":
                allowed, reason = can_disable(
                    b,
                    password_attempt=password_attempt,
                    random_attempt=random_attempt,
                    random_expected=random_expected,
                )
                if not allowed:
                    raise LockedError(reason)
            b.enabled = bool(enabled)
            if enabled and not b.active_since:
                b.active_since = _now().isoformat(timespec="seconds")
            if not enabled:
                b.active_since = None
            self.save()
            self._apply()
            return True

    def toggle_block(
        self,
        name: str,
        *,
        password_attempt=None,
        random_attempt=None,
        random_expected=None,
    ) -> bool:
        with self._lock():
            b = self.find_block(name)
            if not b:
                return False
            return self.set_block_enabled(
                name,
                not b.enabled,
                password_attempt=password_attempt,
                random_attempt=random_attempt,
                random_expected=random_expected,
            )

    # ---------- lifecycle ----------

    def start(self) -> None:
        # Apply monotonic-clock preference before any timing code runs.
        clock.configure(self.config.settings.ignore_time_changes)

        self._proxy.set_block_page(
            self.config.settings.motivational_quote,
            self.config.settings.custom_block_page_html,
        )
        self._proxy.start()
        self._apps.start()
        try:
            enable_proxy("127.0.0.1", self.config.settings.proxy_port)
        except Exception as e:
            log.warning("enable_proxy failed: %s", e)

        # Optional anti-bypass measures
        if self.config.settings.force_protect_termination:
            # Force protect supersedes the simpler `protect_process` and
            # `watchdog_enabled` toggles - it stacks every layer.
            force_protect.enable()
        elif self.config.settings.protect_process:
            selfprotect.enable_kill_protection()
        if (self.config.settings.watchdog_enabled
                and not self.config.settings.force_protect_termination):
            _watchdog.start_watchdog()

        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ff-engine", daemon=True)
        self._thread.start()
        self._apply()

    def shutdown(self) -> None:
        self._stop.set()
        try:
            disable_proxy()
        except Exception:
            pass
        try:
            clear_block_section()
            flush_dns()
        except Exception:
            pass
        try:
            set_task_manager_blocked(False)
        except Exception:
            pass
        try:
            # Tear down force-protect first - it's a superset of the others.
            force_protect.disable()
        except Exception:
            pass
        try:
            selfprotect.disable_kill_protection()
        except Exception:
            pass
        try:
            _watchdog.stop_watchdog()
        except Exception:
            pass
        self._proxy.stop()
        self._apps.stop()

    # ---------- main loop ----------

    def _run(self) -> None:
        last_minute = -1
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                log.exception("engine tick failed: %s", e)
            # Re-apply rules and re-evaluate schedule every 10s
            self._stop.wait(10.0)
            now_m = _now().minute
            if now_m != last_minute:
                last_minute = now_m
                try:
                    self._reset_allowances_if_new_day()
                except Exception:
                    pass

    def _tick(self) -> None:
        self._update_pomodoro()
        self._update_frozen_turkey()
        self._consume_allowances()
        self._apply()

    # ---------- schedule + allowance + blocks ----------

    def _effective_enabled(self, b: BlockList, now: dt.datetime) -> bool:
        # Manual toggle ON wins
        if b.enabled:
            # If an allowance is active with minutes remaining, the block is suspended.
            if b.allowance.minutes_per_day > 0 and b.allowance.minutes_left_today > 0:
                return False
            return True

        # Otherwise, check schedule.
        for slot in b.schedule:
            if _slot_active_now(slot, now):
                if b.allowance.minutes_per_day > 0 and b.allowance.minutes_left_today > 0:
                    return False
                return True
        return False

    def _block_page_context(
        self, active_blocks: List[BlockList], now: dt.datetime
    ) -> tuple[str, str]:
        """Return ``(block_name, detail)`` for the block-page banner.

        Picks the first active block. ``detail`` is its custom message if set,
        otherwise the time left on a timer lock (e.g. "1h 22m left"), otherwise
        empty.
        """
        if not active_blocks:
            return "", ""
        b = active_blocks[0]
        if b.custom_block_message:
            return b.name, b.custom_block_message
        if b.lock.kind == "timer" and b.lock.until:
            try:
                until = dt.datetime.fromisoformat(b.lock.until)
                remaining = until - now
                if remaining.total_seconds() > 0:
                    return b.name, f"{_format_remaining(remaining)} left"
            except ValueError:
                pass
        return b.name, ""

    def _apply(self) -> None:
        with self._lock():
            self._apply_locked()

    def _apply_locked(self) -> None:
        now = _now()
        user = _current_user()

        all_sites: List[str] = []
        all_excepts: List[str] = []
        exe_paths: List[str] = []
        folders: List[str] = []
        windows: List[str] = []
        store: List[str] = []
        active_blocks: List[BlockList] = []

        any_active = False
        for b in self.config.blocks:
            # Per-user gating
            if b.users and user and user not in [u.lower() for u in b.users]:
                continue
            if not self._effective_enabled(b, now):
                continue
            any_active = True
            active_blocks.append(b)
            all_sites.extend(b.sites)
            all_excepts.extend(b.site_exceptions)
            exe_paths.extend(b.app_files)
            folders.extend(b.app_folders)
            windows.extend(b.app_windows)
            store.extend(b.store_apps)

        # Optional DoH blocking (respecting the user's allowlist so services
        # like NextDNS continue working).
        hosts_entries = list(all_sites)
        if any_active and self.config.settings.block_doh:
            hosts_entries.extend(doh_block_list(self.config.settings.doh_allowlist))

        # Apply hosts file
        try:
            if any_active and hosts_entries:
                write_block_section(hosts_entries)
            else:
                clear_block_section()
            flush_dns()
        except PermissionError:
            log.warning("Cannot write hosts file - not elevated?")
        except Exception as e:
            log.debug("hosts apply: %s", e)

        # Update proxy rule set (covers keyword / path / wildcard / *.*)
        self._proxy.set_rules(all_sites, all_excepts)
        self._proxy.set_block_page(
            self.config.settings.motivational_quote,
            self.config.settings.custom_block_page_html,
        )
        # Tell the proxy which block is responsible (for the block-page banner).
        # Guarded so a minimal proxy implementation without this optional hook
        # still works.
        _set_ctx = getattr(self._proxy, "set_block_context", None)
        if callable(_set_ctx):
            _set_ctx(*self._block_page_context(active_blocks, now))

        # Update app blocker
        self._apps.set_rules(exe_paths, folders, windows, store)

        # Advanced policies: active only while at least one block is active
        if any_active:
            if self.config.settings.block_task_manager:
                set_task_manager_blocked(True)
            if self.config.settings.block_time_changes:
                set_time_change_blocked(True)
            # Re-assert the WinINET proxy in case the user tried to turn it off.
            if self.config.settings.revert_proxy_tampering:
                try:
                    enabled, server, bypass = read_proxy()
                    expected = f"127.0.0.1:{self.config.settings.proxy_port}"
                    if (not enabled) or server != expected or (bypass or "") != _DEFAULT_BYPASS:
                        enable_proxy("127.0.0.1", self.config.settings.proxy_port)
                except Exception as e:
                    log.debug("revert_proxy_tampering: %s", e)
        else:
            set_task_manager_blocked(False)
            set_time_change_blocked(False)

        # Self-protection + watchdog can be toggled live too.
        if self.config.settings.force_protect_termination:
            # Strongest mode: enable + reassert every tick so any layer the
            # OS or another tool stripped is restored quickly.
            force_protect.enable()
            force_protect.reassert()
            # The simpler kill-protection ACL is already covered by enable().
            # The simpler single-watchdog must NOT also run, otherwise we'd
            # have three respawners fighting each other.
            _watchdog.stop_watchdog()
        else:
            force_protect.disable()
            if self.config.settings.protect_process:
                selfprotect.enable_kill_protection()
            else:
                selfprotect.disable_kill_protection()
            if self.config.settings.watchdog_enabled and any_active:
                _watchdog.start_watchdog()
            elif not self.config.settings.watchdog_enabled:
                _watchdog.stop_watchdog()

        self._dispatch_block_warnings(active_blocks)
        self._dispatch_lock_warnings(active_blocks, now)

    # ---------- warnings ----------
    #
    # A block's warning fires once each time the block transitions from
    # inactive to active (manual enable, schedule start, pomodoro work phase,
    # or an allowance running out and the block resuming).  Re-applying the
    # same active set must NOT re-fire it, and to avoid popup spam only the
    # first newly-active block's warning is emitted per pass.

    def _effective_warning(self, block: BlockList) -> Optional[WarningConfig]:
        """Return the warning config to fire for ``block``, or ``None``.

        The nested ``block.warning`` is canonical (this is what the UI edits).
        The flat ``block.warning_*`` fields are an alternate surface; if they
        enable a warning we build an equivalent config from them.
        """
        if getattr(block, "warning_enabled", False):
            return WarningConfig(
                enabled=True,
                message=getattr(block, "warning_message", ""),
                sound_path=getattr(block, "warning_sound_path", ""),
                volume=getattr(block, "warning_volume", 80),
                popup_duration_seconds=getattr(block, "warning_popup_duration_seconds", 10),
                fade_enabled=getattr(block, "warning_fade_enabled", True),
                fade_seconds=getattr(block, "warning_fade_seconds", 2),
                always_on_top=getattr(block, "warning_always_on_top", True),
                dismiss_mode=getattr(block, "warning_dismiss_mode", "auto_close"),
            )
        warning = getattr(block, "warning", None)
        if warning is not None and warning.enabled:
            return warning
        return None

    def _dispatch_block_warnings(self, active_blocks: List[BlockList]) -> None:
        """Fire warnings for blocks that just became active (the ``_apply`` path).

        Also re-fires blocks whose warning has a ``repeat_minutes`` interval and
        have stayed active long enough since their last warning (report §16.2).
        """
        seen = getattr(self, "_active_block_names", None)
        if seen is None:
            self._active_block_names = seen = set()
        current = {b.name for b in active_blocks}
        newly_active = [b for b in active_blocks if b.name not in seen]
        self._active_block_names = current

        last = getattr(self, "_last_warning_at", None)
        if last is None:
            self._last_warning_at = last = {}
        now = time.time()

        # Only the first newly-active warning, to avoid popup spam when several
        # blocks start at once.
        for b in newly_active:
            cfg = self._effective_warning(b)
            if cfg is None:
                continue
            self._fire_warning(b.name, cfg, "activated", block=b)
            break

        # Repeat warnings for blocks that have stayed active past their interval.
        newly_names = {b.name for b in newly_active}
        for b in active_blocks:
            if b.name in newly_names:
                continue
            cfg = self._effective_warning(b)
            if cfg is None:
                continue
            rep = int(getattr(cfg, "repeat_minutes", 0) or 0)
            if rep <= 0:
                continue
            prev = last.get(b.name)
            if prev is not None and (now - prev) >= rep * 60:
                self._fire_warning(b.name, cfg, "repeat", block=b)

    def _dispatch_lock_warnings(self, active_blocks: List[BlockList], now: dt.datetime) -> None:
        """Warn when an active block's timer lock expires (report §6.4)."""
        locked = getattr(self, "_locked_block_names", None)
        if locked is None:
            self._locked_block_names = locked = set()
        still_locked: set = set()
        for b in active_blocks:
            if b.lock.kind != "timer" or not b.lock.until:
                continue
            try:
                until = dt.datetime.fromisoformat(b.lock.until)
            except ValueError:
                continue
            if now < until:
                still_locked.add(b.name)
            elif b.name in locked:
                # locked -> unlockable transition while still active
                w = b.warning
                if w.enabled and w.on_lock_unlock:
                    self._fire_warning(b.name, w, "lock_unlocked", block=b)
        self._locked_block_names = still_locked

    def report_unlock_blocked(self, block_name: str) -> None:
        """Called by the UI when a disable attempt is denied by a lock (§6.4)."""
        b = self.find_block(block_name)
        if not b:
            return
        w = b.warning
        if w.enabled and w.on_early_unlock:
            self._fire_warning(b.name, w, "early_unlock", block=b)

    def _fire_pomodoro_warning(self, message: str) -> None:
        """Show a Pomodoro phase warning if phase warnings are enabled (§6.2)."""
        cfg = self.config.settings.pomodoro
        if not cfg.phase_warnings or not message:
            return
        wc = WarningConfig(
            enabled=True,
            message=message,
            sound_path=cfg.warning_sound_path,
            volume=cfg.warning_volume,
            theme="exam",
        )
        block = self.find_block(cfg.target_block)
        self._fire_warning(cfg.target_block or "Pomodoro", wc, "pomodoro", block=block)

    def _fire_warning(
        self,
        block_name: str,
        cfg: WarningConfig,
        reason: str,
        block: Optional[BlockList] = None,
    ) -> None:
        """Deliver one warning to every registered sink (callback/handler/listeners)."""
        event = WarningEvent(
            block_name=block_name,
            message=resolve_warning_message(cfg),
            config=cfg,
        )
        last = getattr(self, "_last_warning_at", None)
        if last is not None:
            last[block_name] = time.time()

        callback = getattr(self, "_warning_callback", None)
        if callback is not None and block is not None:
            try:
                callback(block, reason)
            except Exception:
                log.exception("warning callback failed")

        handler = getattr(self, "_warning_handler", None)
        if handler is not None:
            try:
                handler(event)
            except Exception:
                log.exception("warning handler failed")

        for listener in list(getattr(self, "_warning_listeners", []) or []):
            try:
                listener(event)
            except Exception:
                log.exception("warning listener failed")

    def _emit_newly_active_warnings(self, active_blocks: Dict) -> None:
        """Emit handler events for newly-active blocks.

        ``active_blocks`` maps a stable key (e.g. ``(index, name)``) to its
        :class:`BlockList`.  Events for blocks whose warning is enabled are
        sent to the handler, or queued until a handler is registered.
        """
        prev = getattr(self, "_previous_active_block_keys", None)
        if prev is None:
            self._previous_active_block_keys = prev = set()
        current_keys = set(active_blocks.keys())
        newly = current_keys - prev
        self._previous_active_block_keys = current_keys

        for key in sorted(newly, key=lambda k: str(k)):
            block = active_blocks[key]
            warning = getattr(block, "warning", None)
            if warning is None or not warning.enabled:
                continue
            event = WarningEvent(
                block_name=block.name,
                message=resolve_warning_message(warning),
                config=warning,
            )
            handler = getattr(self, "_warning_handler", None)
            if handler is None:
                self._pending_warning_events.append(event)
            else:
                try:
                    handler(event)
                except Exception:
                    log.exception("warning handler failed")

    def _emit_block_activation_warnings(self, active_blocks: List[BlockList]) -> None:
        """Notify listeners for the first newly-active block with an enabled warning.

        Listeners are invoked as ``listener(block_name, warning_config)``.  This
        is an alternate (currently unused by ``_apply``) entry point whose
        two-argument convention is pinned by ``tests/test_engine_warnings.py``;
        the ``_apply``/``_fire_warning`` path uses the single-``WarningEvent``
        convention instead.
        """
        seen = getattr(self, "_active_warning_blocks", None)
        if seen is None:
            self._active_warning_blocks = seen = set()
        current = {b.name for b in active_blocks}
        newly_active = [b for b in active_blocks if b.name not in seen]
        self._active_warning_blocks = current

        for b in newly_active:
            warning = getattr(b, "warning", None)
            if warning is None or not warning.enabled:
                continue
            for listener in list(getattr(self, "_warning_listeners", []) or []):
                try:
                    listener(b.name, warning)
                except Exception:
                    log.exception("warning listener failed")
            break  # only the first newly-active warning, to avoid popup spam

    # ---------- allowances ----------

    def _reset_allowances_if_new_day(self) -> None:
        with self._lock():
            today = _now().date().isoformat()
            dirty = False
            for b in self.config.blocks:
                if b.allowance.minutes_per_day <= 0:
                    continue
                if b.allowance.last_reset != today:
                    b.allowance.minutes_left_today = b.allowance.minutes_per_day
                    b.allowance.last_reset = today
                    dirty = True
            if dirty:
                self.save()

    def _consume_allowances(self) -> None:
        """If the user is actively viewing a blocked resource, burn allowance minutes."""
        with self._lock():
            # We approximate "in foreground with active input" via idle detection.
            if idle_seconds() > 180:  # 3 min idle -> don't count
                return
            # Use a monotonic delta: immune to system-clock moves, so a user can't
            # refill allowance by rewinding the wall clock.
            now_mono = time.monotonic()
            last_tick = getattr(self, "_last_allowance_tick", None)
            if last_tick is None:
                self._last_allowance_tick = now_mono
                return
            elapsed = now_mono - last_tick
            if elapsed < 30:
                return
            self._last_allowance_tick = now_mono
            minutes_elapsed = elapsed / 60.0
            dirty = False
            for b in self.config.blocks:
                if b.allowance.minutes_per_day <= 0:
                    continue
                if b.allowance.minutes_left_today <= 0:
                    continue
                # Only burn if block was manually enabled or its schedule window says so;
                # otherwise there is nothing to bypass.
                now_dt = _now()
                scheduled = any(_slot_active_now(s, now_dt) for s in b.schedule)
                if not (b.enabled or scheduled):
                    continue
                b.allowance.minutes_left_today = max(
                    0, int(round(b.allowance.minutes_left_today - minutes_elapsed))
                )
                dirty = True
            if dirty:
                self.save()

    def grant_allowance(self, block_name: str, minutes: int) -> bool:
        with self._lock():
            b = self.find_block(block_name)
            if not b:
                return False
            b.allowance.minutes_left_today = max(0, b.allowance.minutes_left_today + int(minutes))
            if b.allowance.last_reset == "":
                b.allowance.last_reset = _now().date().isoformat()
            if b.allowance.minutes_per_day < b.allowance.minutes_left_today:
                b.allowance.minutes_per_day = b.allowance.minutes_left_today
            self.save()
            self._apply()
            return True

    # ---------- pomodoro ----------

    def start_pomodoro(self) -> None:
        cfg = self.config.settings.pomodoro
        if not cfg.enabled or not cfg.target_block:
            return
        self._pomo_phase = "work"
        self._pomo_phase_until = _now() + dt.timedelta(minutes=cfg.work_minutes)
        self._pomo_cycle = 0
        self._pomo_paused_remaining = None
        self.set_block_enabled(cfg.target_block, True)
        self._fire_pomodoro_warning(cfg.work_message)

    def stop_pomodoro(self) -> None:
        cfg = self.config.settings.pomodoro
        self._pomo_phase = "idle"
        self._pomo_phase_until = None
        self._pomo_paused_remaining = None
        if cfg.target_block:
            self.set_block_enabled(cfg.target_block, False)

    def pause_pomodoro(self) -> None:
        """Freeze the countdown, remembering how much time was left."""
        if self._pomo_phase == "idle" or self._pomo_paused_remaining is not None:
            return
        if self._pomo_phase_until is not None:
            self._pomo_paused_remaining = max(
                0.0, (self._pomo_phase_until - _now()).total_seconds()
            )
        else:
            self._pomo_paused_remaining = 0.0

    def resume_pomodoro(self) -> None:
        """Resume a paused countdown from where it left off."""
        if self._pomo_paused_remaining is None:
            return
        self._pomo_phase_until = _now() + dt.timedelta(seconds=self._pomo_paused_remaining)
        self._pomo_paused_remaining = None

    def is_pomodoro_paused(self) -> bool:
        return self._pomo_paused_remaining is not None

    def skip_pomodoro_phase(self) -> None:
        """End the current phase immediately and advance to the next one."""
        if self._pomo_phase == "idle":
            return
        self._pomo_paused_remaining = None
        self._pomo_phase_until = _now()  # makes _update_pomodoro flip now
        self._update_pomodoro()

    def pomodoro_status(self) -> Optional[dict]:
        """Return the live Pomodoro state, or ``None`` when idle.

        Keys: ``phase`` (work|break|long_break), ``remaining_seconds``,
        ``paused`` (bool), ``cycle`` (1-based), ``cycles``.
        """
        if self._pomo_phase == "idle":
            return None
        cfg = self.config.settings.pomodoro
        if self._pomo_paused_remaining is not None:
            remaining = int(self._pomo_paused_remaining)
        elif self._pomo_phase_until is not None:
            remaining = max(0, int((self._pomo_phase_until - _now()).total_seconds()))
        else:
            remaining = 0
        return {
            "phase": self._pomo_phase,
            "remaining_seconds": remaining,
            "paused": self._pomo_paused_remaining is not None,
            "cycle": self._pomo_cycle + 1,
            "cycles": cfg.cycles,
        }

    def _update_pomodoro(self) -> None:
        cfg = self.config.settings.pomodoro
        if not cfg.enabled or self._pomo_phase == "idle":
            return
        # While paused the countdown is frozen.
        if self._pomo_paused_remaining is not None:
            return
        if self._pomo_phase_until and _now() < self._pomo_phase_until:
            return
        # Phase flip
        if self._pomo_phase in ("break", "long_break"):
            self._pomo_cycle += 1
            if self._pomo_cycle >= cfg.cycles:
                self._fire_pomodoro_warning(cfg.complete_message)
                self.stop_pomodoro()
                return
            self._pomo_phase = "work"
            self._pomo_phase_until = _now() + dt.timedelta(minutes=cfg.work_minutes)
            if cfg.target_block:
                self.set_block_enabled(cfg.target_block, True)
            self._fire_pomodoro_warning(cfg.work_message)
        else:  # was "work" -> break
            # Long break every Nth completed work cycle (report §3.9).
            every = int(getattr(cfg, "long_break_every", 0) or 0)
            completed = self._pomo_cycle + 1  # this work cycle just finished
            if every > 0 and completed % every == 0:
                self._pomo_phase = "long_break"
                mins = int(getattr(cfg, "long_break_minutes", cfg.break_minutes))
            else:
                self._pomo_phase = "break"
                mins = cfg.break_minutes
            self._pomo_phase_until = _now() + dt.timedelta(minutes=mins)
            if cfg.target_block:
                self.set_block_enabled(cfg.target_block, False)
            self._fire_pomodoro_warning(cfg.break_message)

    # ---------- frozen turkey ----------

    def set_frozen_action_handler(
        self, handler: Optional[Callable[[str, int], None]]
    ) -> None:
        """Register a UI handler for the Frozen Turkey pre-action countdown.

        When set, entering the Frozen Turkey window calls ``handler(action,
        warn_seconds)`` *instead* of running the action immediately, so the UI
        can show a cancellable countdown and then call
        :meth:`perform_frozen_action` (or :meth:`cancel_frozen_turkey`).

        With no handler registered (headless mode) the engine runs the action
        directly after the same delay, exactly as before.
        """
        self._frozen_action_handler = handler

    def cancel_frozen_turkey(self) -> None:
        """Abort the pending Frozen Turkey action for the current window."""
        self._frozen_cancelled_window = True
        self._frozen_turkey_actioned = True  # don't re-fire until the window resets

    def perform_frozen_action(self, action: str) -> None:
        """Execute a Frozen Turkey action (lock / logoff / shutdown)."""
        if self._frozen_cancelled_window:
            return
        if action == "lock":
            try:
                import ctypes
                ctypes.windll.user32.LockWorkStation()
            except Exception:
                pass
        elif action == "logoff":
            try:
                subprocess.Popen(["shutdown", "/l"], creationflags=0x08000000)
            except Exception:
                pass
        elif action == "shutdown":
            try:
                subprocess.Popen(["shutdown", "/s", "/t", "60",
                                  "/c", "FocusFortress Frozen Turkey"],
                                 creationflags=0x08000000)
            except Exception:
                pass

    def _update_frozen_turkey(self) -> None:
        ft = self.config.settings.frozen_turkey
        if not ft.enabled:
            self._reset_frozen_state()
            return
        now = _now()
        if now.weekday() not in ft.days:
            self._reset_frozen_state()
            return
        try:
            s = dt.time.fromisoformat(ft.start)
            e = dt.time.fromisoformat(ft.end)
        except ValueError:
            return
        t = now.time()
        in_window = (s <= t <= e) if s <= e else (t >= s or t <= e)
        if not in_window:
            # Left the window - re-arm so the next entry fires again.
            self._reset_frozen_state()
            return
        if self._frozen_turkey_actioned or self._frozen_cancelled_window:
            # Already actioned/cancelled this window; don't re-fire every tick.
            return

        warn_seconds = int(getattr(ft, "warn_seconds", 60) or 0)
        handler = getattr(self, "_frozen_action_handler", None)

        if warn_seconds > 0 and handler is not None:
            # Delegate the countdown to the UI (it will call back to
            # perform_frozen_action / cancel_frozen_turkey).
            self._frozen_turkey_actioned = True
            try:
                handler(ft.action, warn_seconds)
            except Exception:
                log.exception("frozen action handler failed")
                # Handler broke - fall back to firing directly so the rule
                # still has teeth.
                self.perform_frozen_action(ft.action)
            return

        if warn_seconds > 0:
            # Headless: count down internally before firing.
            if self._frozen_pending_deadline is None:
                self._frozen_pending_deadline = time.monotonic() + warn_seconds
                return
            if time.monotonic() < self._frozen_pending_deadline:
                return

        # No warning configured (or countdown elapsed): fire now.
        self._frozen_turkey_actioned = True
        self._frozen_pending_deadline = None
        self.perform_frozen_action(ft.action)

    def _reset_frozen_state(self) -> None:
        self._frozen_turkey_actioned = False
        self._frozen_pending_deadline = None
        self._frozen_cancelled_window = False

