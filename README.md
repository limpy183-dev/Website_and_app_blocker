# FocusFortress

A **Windows-only** website and application blocker inspired by Cold Turkey Blocker, built with **Python 3.10+** and **PyQt6**.

FocusFortress enforces blocks at the OS level — the hosts file, a local HTTP/HTTPS proxy, a process watcher, and Windows policy tweaks — and is designed to *resist being disabled* while a block is active. It runs headless in the system tray, self-elevates via UAC, and stores everything locally. No accounts, no cloud, no telemetry.

> **Status:** actively developed. The full per-block **warning & alarm** layer is implemented; the test suite (31 tests) passes and the package compiles cleanly.

---

## Table of contents

- [Features](#features)
- [Requirements](#requirements)
- [Install](#install)
- [Running the app](#running-the-app)
- [Command-line interface](#command-line-interface)
- [Warnings & alarms](#warnings--alarms)
- [How it works](#how-it-works-architecture)
- [Anti-bypass & self-protection](#anti-bypass--self-protection)
- [Data & privacy](#data--privacy)
- [Development](#development)
- [Packaging](#packaging)
- [Project layout](#project-layout)
- [Limitations & caveats](#limitations--caveats)

---

## Features

### 🌐 Website blocking
- Block whole domains including subdomains and mobile variants (`www.`, `m.`, `mobile.`, `cdn.` …) via the **hosts file**.
- Block specific paths/URLs — e.g. a YouTube channel (`youtube.com/mkbhd`) or subreddit (`reddit.com/r/funny`).
- **Keyword / wildcard** rules (`google.com/*q=*unicorn*`) enforced by the bundled local proxy.
- Block the **entire internet** (`*.*`) with per-list exceptions.
- Import/export lists and a one-click **default distractions** set.
- Optional **DoH blocking** (well-known DNS-over-HTTPS endpoints) with an allowlist, so browsers can't tunnel around the hosts file.

### 🖥️ Application blocking
- Block by **`.exe` path**.
- Block by **folder** (every executable inside, recursively).
- Block **Microsoft Store / UWP** apps by package name / AppUserModelID.
- Block by **window-title substring**.

### 🔔 Warnings & alarms *(per-block)*
- Show a custom **popup** (and optionally play a **sound**) when a block becomes active.
- Triggers: manual enable, schedule start, **allowance running out**, **Pomodoro phase changes**, **timer-lock expiry**, a **blocked early-unlock attempt**, and a configurable **repeat-every-N-minutes**.
- Popup **modes**: centered, compact (corner), or full-screen; six **themes** plus colour overrides; optional **image / GIF**.
- **Audio**: pick your own MP3/WAV/OGG or a built-in tone (beep / alarm / chime / siren); volume, looping, and a stop-after-N-seconds cap; always fails safe (a missing file never blocks the popup).
- **Dismiss modes**: auto-close, click-to-close, type-to-dismiss, hold-to-dismiss, with an optional "close button appears after N seconds" delay. `Esc` is always an escape hatch — the popup never traps you.
- **Presets** (calm reminder, red alert, study mode, sleep reminder, gaming limit, exam panic), **random message pools**, and **JSON import/export** of warning profiles.
- See the [Warnings & alarms](#warnings--alarms) section for the full reference.

### 🗓️ Scheduling, Pomodoro & allowances
- Weekly **schedule** grid — a block auto-activates inside its time slots.
- **Pomodoro** cycles (work/break/cycles) that drive a target block, with optional phase-change warnings.
- **Allowances** — grant yourself a daily quota; it counts down only while you're actively using a blocked resource (foreground + idle detection), then the block resumes.
- **Frozen Turkey** — force a **lock / log-off / shutdown** on a schedule.
- **Pause for a cause** — a 10-minute break after an (optional) donation prompt.

### 🔒 Lock methods
The gate that decides whether you're *allowed* to turn an active block off:
- **Timer** — unlock after a delay / at an absolute time.
- **Random** — type a long random string (1–999 chars).
- **Range** — only changeable inside (or outside) a time window.
- **Restart** — requires a genuine reboot to disarm (compares against system boot time).
- **Password** — salted SHA-256 secret.

### 🛡️ Anti-bypass *(opt-in, all default OFF)*
Layered and increasingly aggressive — see [Anti-bypass & self-protection](#anti-bypass--self-protection):
- Block **system time changes** and **Task Manager** while a block is active.
- **Process kill-protection**, a **watchdog** respawner, and a strongest-tier **Force Protect** mode.
- **Clock-tamper protection** (monotonic clock) so moving the system clock can't shorten a timer or skip a schedule.
- **Proxy-tamper reversion** re-asserts WinINET proxy settings if you try to turn them off.

### 📊 Statistics & customization
- Local-only tracking of time **per site** and **per app**; export to JSON or clear on demand.
- Custom **block page** (HTML or a motivational quote).
- **Per-Windows-user** targeting for each block.
- Dark, modern PyQt6 UI with a sidebar + stacked pages, plus full system-tray operation.

---

## Requirements

- **Windows 10 / 11**
- **Python 3.10+**
- **Admin privileges** — the app prompts for UAC elevation and relaunches itself elevated.

Most enforcement (hosts file, policies, proxy registration) only takes effect when elevated. Without admin the engine logs warnings and degrades gracefully rather than crashing.

Dependencies (`requirements.txt`):

```
PyQt6>=6.6.0
psutil>=5.9.0
pywin32>=306
pydivert>=2.1.0 ; platform_system=="Windows"
requests>=2.31.0
```

---

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## Running the app

```powershell
# Launch the GUI (self-elevates via UAC; only one GUI instance runs at a time)
python -m focusfortress

# Start straight to the system tray, no window
python -m focusfortress --background
```

The engine runs fully headless — the window is just a controller over it, so closing the window keeps blocks enforced in the tray.

---

## Command-line interface

Operate on block lists by name without the GUI:

```powershell
python -m focusfortress cli list                     # list blocks and their on/off state
python -m focusfortress cli start  "Distractions"    # enable a block
python -m focusfortress cli stop   "Distractions"    # disable a block
python -m focusfortress cli toggle "Distractions"    # flip a block

# Arm a lock on a block (also enables it). Exactly one method is required:
python -m focusfortress cli lock "Work" --timer 02:30                 # duration HH:MM from now
python -m focusfortress cli lock "Work" --until 2026-06-01T09:00      # absolute ISO datetime
python -m focusfortress cli lock "Work" --random 48                   # 48-char random unlock string
python -m focusfortress cli lock "Work" --restart                    # reboot to unlock
python -m focusfortress cli lock "Work" --password "s3cret"           # password to unlock
python -m focusfortress cli lock "Work" --range 22:00-06:00           # changes only allowed outside the window
```

---

## Warnings & alarms

Each block carries its own warning configuration (edited in **Blocks → Warning**). A warning fires **once** each time the block transitions from inactive to active, and the popup is shown on the Qt main thread (the engine only ever emits data).

### Per-block options

| Group | Options |
|---|---|
| **Message** | Single message, or several lines that are picked from at random. |
| **Sound** | Browse for MP3/WAV/OGG, or use a built-in tone (**beep / alarm / chime / siren**); volume; loop until close; stop after N seconds. |
| **Popup** | Mode — **centered / compact / full-screen**; visible-for duration; fade-out; always-on-top; theme (**default / red_alert / calm / exam / minimal / high_contrast**); optional **image / GIF**; text/background colour overrides. |
| **Dismiss** | **auto_close**, **click_to_close**, **type_to_dismiss**, **hold_to_dismiss**; optional "close button after N seconds" delay. `Esc` always closes. |
| **Triggers** | Block activation (always); **repeat every N minutes**; **timer-lock finished**; **blocked early-unlock attempt**. |

### Triggers in detail
- **Block activation** — manual enable, a schedule slot opening, a Pomodoro work phase starting, or an **allowance hitting zero** and the block resuming.
- **Repeat** — re-shows the warning on an interval while the block stays active.
- **Timer-lock expiry** — warns when a timer lock counts down to unlockable.
- **Early-unlock blocked** — warns when you try to disable a locked block and are denied.
- **Pomodoro phases** *(configured on the Pomodoro tab)* — separate work / break / cycle-complete messages and sound.

### Presets, profiles & testing
- **Presets** fill in a complete style you can then tweak: `calm_reminder`, `red_alert`, `study_mode`, `sleep_reminder`, `gaming_limit`, `exam_panic`.
- **Built-in sounds** are synthesised on first use into `%PROGRAMDATA%\FocusFortress\sounds\` (no binary assets are shipped).
- **Import / Export** a warning profile as JSON to reuse it across blocks or machines.
- **Test warning** / **Test sound** buttons preview your settings without changing block state.

---

## How it works (architecture)

A single executable dispatches on the first argument: *(default)* → GUI, `cli` → CLI, `watchdog` → sidecar respawner.

### The engine is the center (`engine.py`)
`Engine` is a singleton with a daemon thread that **ticks every 10 s**. Its `_apply()` method is the heart of the system; each pass it:
1. Computes the set of **effective-active** blocks (manually enabled **or** inside a schedule slot, minus any active allowance, filtered by Windows user).
2. Unions every active block's rules and pushes them into the four enforcement layers below.
3. Re-asserts Windows policies, proxy settings, and self-protection — so tampering is reverted on the next tick (`_apply()` is idempotent by design).

The same tick drives Pomodoro phase flips, Frozen Turkey, allowance burn-down (gated by idle detection), and **warning events**. UI/CLI mutations apply immediately rather than waiting for the tick.

### Four enforcement layers (`blocking/`)
- **`hosts.py`** — writes domains into the Windows hosts file between markers (expanding `www./m./mobile./cdn.` variants for both `127.0.0.1` and `::1`), then flushes DNS.
- **`proxy.py`** — a local HTTP/HTTPS proxy (default `127.0.0.1:58123`) registered as the WinINET proxy. Catches what the hosts file can't (paths, keywords, wildcards, `*.*`) and serves the block page. It **never MITMs TLS** — HTTPS blocking is host-level.
- **`patterns.py`** — compiles FocusFortress patterns to regexes for the proxy.
- **`apps.py`** — `AppBlocker` polls ~1 s and kills processes matching an exe path, containing folder, window-title substring, or UWP package.

### Persistence (`config_store.py`, `paths.py`, `models.py`)
State is JSON under `%PROGRAMDATA%\FocusFortress\` (`config.json`, `stats.json`, `state.json`) — **admin-writable, user-readable by design**, so a non-admin user can't edit their own block list. Writes are atomic under a lock; a corrupt config is backed up and regenerated. `AppConfig.from_dict()` tolerates missing/unknown keys, so old config files keep loading as new fields are added.

---

## Anti-bypass & self-protection

All opt-in and default OFF, increasingly aggressive:

- **`selfprotect.py`** — DACL-denies `PROCESS_TERMINATE` on our own process (Task Manager / `taskkill` can't close FocusFortress while a block is active).
- **`watchdog.py`** — a sidecar process that respawns the app if it's killed while a block is active.
- **`force_protect.py`** — the strongest mode: stacks the DACL deny + console-signal swallowing + HIGH priority + a *pair* of mutual watchdogs. When on, it **supersedes** the simpler `protect_process` / `watchdog_enabled` toggles.
- **`advanced.py`** — toggles Task Manager and system-time-change policies (active only while a block is active).
- **`clock.py`** — when *Ignore time changes* is on, all scheduling/timer logic reads a monotonic-derived clock anchored to a persisted baseline, so moving the system clock can't shorten a timer lock or skip a schedule window.

---

## Data & privacy

Everything is stored **locally** in `%PROGRAMDATA%\FocusFortress\`:

| File / dir | Contents |
|---|---|
| `config.json` | Blocks, schedules, settings, warning configs |
| `stats.json` | Local per-site / per-app time tracking |
| `state.json` | Runtime state (active locks, etc.) |
| `sounds/` | Synthesised built-in warning tones |
| `blockpage/` | Custom block-page assets |

**No telemetry, no cloud, no accounts.**

---

## Development

This directory **is** a git repo, but the package is imported by path — no install needed to run the tests.

```powershell
# Whole suite
python -m pytest tests/

# A single test
python -m pytest tests/test_warning_engine.py::WarningEngineTests::test_disabled_warning_is_tracked_without_emitting

# Static check + GUI smoke test
python -m compileall focusfortress tests
python _test_launch.py        # launches the window, prints diagnostics, exits
```

**Cross-platform tests.** Windows-specific imports are guarded so the package imports cleanly on macOS/Linux, and the tests run headless. Qt-based tests use the offscreen platform:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/
```

---

## Packaging

```powershell
pip install pyinstaller
pyinstaller --noconfirm --windowed --name FocusFortress --uac-admin -i icon.ico focusfortress/__main__.py
```

---

## Project layout

```
focusfortress/
├── __main__.py          # entry point: GUI / cli / watchdog dispatch + UAC self-elevation
├── engine.py            # singleton orchestrator; _apply() enforces + emits warnings
├── models.py            # dataclass config tree (AppConfig → BlockList → WarningConfig …)
├── config_store.py      # atomic JSON persistence
├── locks.py             # can_disable() gate for the five lock methods
├── clock.py             # clock-tamper-resistant "now"
├── warnings.py          # warning presets + random-message resolution
├── sounds.py            # synthesised built-in sound pack
├── blocking/            # hosts.py, proxy.py, patterns.py, apps.py, doh.py, winproxy.py
├── selfprotect.py / watchdog.py / force_protect.py / advanced.py   # anti-bypass tiers
└── ui/                  # PyQt6: app.py, main_window.py, warning_popup.py, theme.py, widgets.py
    └── tabs/            # blocks_tab, schedule_tab, pomodoro_tab, frozen_tab, …
tests/                   # unit tests (run anywhere; Qt tests use offscreen)
docs/                    # design spec + implementation plan for the warnings feature
```

---

## Limitations & caveats

- **Hosts-file blocking** covers most browser traffic; some browsers' DNS-over-HTTPS can bypass it — the local proxy (and optional DoH blocking) close that gap for HTTP/S.
- The proxy **does not MITM TLS**, so HTTPS rules are enforced at the host level (path/keyword rules apply to plain HTTP and to host decisions on `CONNECT`).
- Kernel-mode (WFP) enforcement is out of scope for a pure-Python project; comparable results come from hosts + proxy + process watcher + policy.
- **Full-screen games** may render above the warning popup (especially exclusive full-screen); the sound still plays, and borderless-windowed games show the popup reliably.
- Task Manager and time-change blocking use Windows **policies that require admin**.

---

*FocusFortress is a personal/educational project. No license has been specified yet — if you intend to reuse it, open an issue to discuss.*
