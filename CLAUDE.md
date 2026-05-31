# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FocusFortress is a **Windows-only** website/application blocker (a Cold Turkey Blocker clone) built with Python 3.10+ and PyQt6. It enforces blocks at the OS level (hosts file, a local proxy, a process killer, and Windows policy tweaks) and resists being disabled while a block is active. It requires admin privileges and self-elevates via UAC.

## Commands

```powershell
# Setup
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt

# Run the GUI (relaunches itself elevated if not already admin; kills any other GUI instance)
python -m focusfortress
python -m focusfortress --background      # start to tray, no window

# CLI (no GUI) — operates on a block list by name
python -m focusfortress cli list
python -m focusfortress cli start|stop|toggle "Distractions"
python -m focusfortress cli lock "Work" --timer 02:30   # also --until/--random/--restart/--password/--range

# Tests (run from repo root; the package is imported by path, no install needed)
python -m pytest tests/                    # whole suite
python -m pytest tests/test_warning_engine.py::WarningEngineTests::test_disabled_warning_is_tracked_without_emitting   # single test
python -m unittest tests.test_warnings -v  # the plan's tests use unittest

# Static check + GUI smoke test
python -m compileall focusfortress tests
python _test_launch.py                     # launches the window, prints diagnostics, exits (sets FOCUSFORTRESS_NO_ELEVATE=1)

# Package
pyinstaller --noconfirm --windowed --name FocusFortress --uac-admin -i icon.ico focusfortress/__main__.py
```

Notes: this directory is **not** a git repo. Most enforcement (hosts file, policies) only works when run elevated; without admin the engine logs warnings and degrades rather than crashing. Tests are designed to import and run on non-Windows too (see "Cross-platform" below).

## Architecture

### Process model (`__main__.py`)
A single executable dispatches on the first argv: default → GUI, `cli` → `cli.py`, `watchdog` → sidecar respawner. The GUI path calls `ensure_admin()` (relaunches elevated) then `_kill_other_instances()` so only one GUI runs at a time. The `watchdog` and `cli` sub-invocations deliberately skip the elevation/kill dance.

### The engine is the center (`engine.py`)
`Engine` is a singleton (`Engine.instance()`) with a daemon thread that ticks every 10s. **`_apply()` is the heart of the system** and the place to understand first. Each call it:
1. Computes the set of *effective-active* blocks via `_effective_enabled()` — a block is active if manually enabled **or** inside a `ScheduleSlot`, **unless** an allowance has minutes left, and it's filtered out if the current Windows user isn't in `block.users`.
2. Unions every active block's rules and pushes them into the four enforcement subsystems (below).
3. Re-asserts Windows policies, proxy settings, and self-protection — so user tampering is reverted on the next tick. `_apply()` is idempotent by design.

The same tick also drives pomodoro phase flips, Frozen Turkey (scheduled lock/logoff/shutdown), allowance burn-down (gated by idle detection), and warning events. CLI/UI mutations call `set_block_enabled()` / `toggle_block()` which save config and call `_apply()` immediately rather than waiting for the tick.

### Four enforcement layers (`blocking/`)
- **`hosts.py`** — writes domains into the Windows hosts file between `# >>> FocusFortress begin/end` markers, expanding each to `www./m./mobile./cdn.` etc. variants (both `127.0.0.1` and `::1`), then flushes DNS. Only bare domains; wildcards/paths are rejected here.
- **`proxy.py`** — a local HTTP/HTTPS proxy (default `127.0.0.1:58123`) registered as the WinINET proxy via `winproxy.py`. Catches what the hosts file can't: path rules, keyword/wildcard rules, and `*.*` (block-the-internet). It **never MITMs TLS** — `CONNECT` is blindly tunneled, so HTTPS blocking is host-level only. Serves the block page. Read the module docstring before touching framing/keep-alive logic.
- **`patterns.py`** — compiles FocusFortress patterns to regexes for the proxy: `*` is a wildcard, a bare `facebook.com` matches all subdomains + paths, `*.*` means block everything. `hosts.py` and `proxy.py` interpret the same `BlockList.sites` strings differently (hosts takes domains, proxy takes the full pattern set).
- **`apps.py`** — `AppBlocker` polls every 1s and `psutil.kill()`s processes matching exe path, containing folder, window-title substring (via `win32gui.EnumWindows`), or UWP package name.

### Lock methods (`locks.py`)
`can_disable(block, ...)` is the gate the UI consults before letting a user turn off an active block. It returns `(allowed, reason)` for kinds `timer|random|range|restart|password`. The `restart` lock compares `clock.boot_time()` against `block.active_since`, so it only unlocks after a real reboot.

### Clock-tamper protection (`clock.py`)
**All scheduling/timer logic must read "now" through `clock.wall_now()` (the engine wraps it as `_now()`), never `datetime.now()` directly.** When `settings.ignore_time_changes` is on, `wall_now()` returns a monotonic-derived time anchored to a persisted wall baseline, so moving the system clock cannot shorten a timer lock or skip a schedule window.

### Anti-bypass (opt-in, all default OFF)
Layered and increasingly aggressive: `selfprotect.py` (DACL-denies `PROCESS_TERMINATE` on our own process) < `watchdog.py` (sidecar that respawns us if killed while a block is active) < `force_protect.py` (the strongest mode: stacks the DACL deny + console-signal swallowing + HIGH priority + a *pair* of mutual watchdogs that respawn each other, active unconditionally). `force_protect_termination` **supersedes** `protect_process`/`watchdog_enabled` — when it's on, the engine disables the simpler single watchdog so respawners don't fight. `advanced.py` toggles the Task Manager and system-time-change policies (active only while a block is active).

### Persistence (`config_store.py`, `paths.py`, `models.py`)
State is JSON under `%PROGRAMDATA%\FocusFortress\` (`config.json`, `stats.json`, `state.json`). That location is **admin-writable, user-readable by design** — a non-admin user can't edit their own block list. Writes are atomic (tmp file + `replace`) under an `RLock`; a corrupt `config.json` is backed up and regenerated. `models.py` holds the dataclass tree (`AppConfig` → `blocks: [BlockList]` + `settings: GlobalSettings`); `AppConfig.from_dict()` parses nested dataclasses separately and defaults missing keys, so old config files keep loading after new fields are added.

### UI (`ui/`)
PyQt6. `app.py` bootstraps the QApplication (system tray, dark theme, starts the engine and `StatsTracker`) and keeps running with no window open. `main_window.py` is a **sidebar + `QStackedWidget`** (not a `QTabWidget`); the pages live in `ui/tabs/`. The engine runs fully headless — the UI is just a controller over it. `stats.py` tracks per-site/per-app time locally by registering a proxy observer and polling the foreground window.

## Conventions & gotchas

- **Windows-only, but tests run anywhere.** Windows-specific imports are guarded (e.g. `apps.py` `_HAVE_WIN32`, `force_protect.py` is a no-op off-Windows) so the package imports cleanly for unit tests on macOS/Linux.
- **Subprocess calls pass `creationflags=0x08000000`** (CREATE_NO_WINDOW) to avoid console-window flashes — match this when adding shell-outs.
- **Never call `datetime.now()` in schedule/lock/timer code** — go through `clock.wall_now()` / engine `_now()` (see clock-tamper section).
- **A `BlockList.sites` entry is consumed by both hosts and proxy layers** with different semantics — verify a pattern change against both `hosts._extract_domain` and `patterns._pattern_to_regex`.

## Warnings feature (implemented)

A per-block warning/alarm layer is implemented and the whole `tests/` suite passes. Design + plan live in `docs/superpowers/` (`specs/...-warnings-design.md`, `plans/...-warnings.md`); the source spec is `Implementation_report.txt`.

All report versions (V1–V5) are now implemented.

- **Data model:** `models.WarningConfig` (nested at `BlockList.warning`) is canonical — this is what the UI edits and the engine reads. The nine documented core fields are always serialised; **every other field** (`messages`, `theme`, `popup_mode`, `image_path`, `text_color`/`background_color`, `loop_sound`, `sound_max_seconds`, `close_delay_seconds`, `hold_seconds`, `repeat_minutes`, `on_lock_unlock`, `on_early_unlock`) is pruned from `to_dict` when equal to its default (`_CORE_WARNING_KEYS` + the generic prune loop), so legacy/simple configs round-trip to exactly the core shape. `AppConfig.from_dict` drops unknown keys via `_only_known`. `BlockList` also has flat `warning_*` fields — an **alternate** flat-config surface (note: `warning_popup_duration_seconds` defaults to 10 there vs 8 on the nested config); the engine treats a warning as active if *either* surface is enabled. `PomodoroConfig` carries phase-warning fields (`phase_warnings`, `work/break/complete_message`, `warning_sound_path`, `warning_volume`).
- **Engine:** emits data-only `WarningEvent`s; `_apply()` → `_dispatch_block_warnings()` fires the first newly-active block's warning once per inactive→active transition (manual/schedule/pomodoro/allowance-expiry) and re-fires on a `repeat_minutes` interval. `_dispatch_lock_warnings()` warns when a timer lock expires (`on_lock_unlock`); `report_unlock_blocked()` (called by the Blocks UI) warns on a denied disable attempt (`on_early_unlock`); `_fire_pomodoro_warning()` fires on Pomodoro phase flips. Registration styles reconciled: `add_warning_listener` (event, used by the UI), `set_warning_handler` (event, with pending-flush), `set_warning_callback` (`block, reason`); `_emit_newly_active_warnings(dict)` / `_emit_block_activation_warnings(list)` are alternate entry points.
- **Sounds:** `focusfortress/sounds.py` synthesises a built-in WAV "sound pack" (beep/alarm/chime/siren) into `%PROGRAMDATA%\FocusFortress\sounds` (no binary assets shipped); `ensure_builtin_sounds()` is fail-soft. Presets reference these via `builtin_sound` (resolved only when a sound map is passed to `apply_warning_preset`, so unit tests stay filesystem-free).
- **UI:** `focusfortress/ui/warning_popup.py` owns `WarningManager` + `WarningPopup` — centered/compact/full-screen modes, per-theme styling + colour overrides, optional image/GIF (`QPixmap`/`QMovie`), QtMultimedia audio (loop + max-seconds cap, stops on close, fails safe), and auto-close/click-to-close/type-to-dismiss/hold-to-dismiss with a `close_delay_seconds` "button appears after N s" gate (Esc is always an escape). `MainWindow` bridges engine events to the Qt thread via a `pyqtSignal`. The Blocks **Warning** sub-tab (`blocks_tab._build_warning_tab` / `_save_warning`) edits the nested config with presets, built-in-sound picker, image picker, all popup/strict options, lock-trigger checkboxes, and Import/Export profile (JSON). The **Pomodoro** tab edits phase warnings.
