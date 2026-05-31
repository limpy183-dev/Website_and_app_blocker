# FocusFortress

A Windows-only website and application blocker inspired by Cold Turkey Blocker, built with Python + PyQt6.

## Features

### Website Blocking
- Block whole domains (incl. subdomains & mobile versions) via the hosts file
- Import/export categories and default distraction lists
- Block specific YouTube channels (`youtube.com/<channel>`)
- Block specific URLs (`reddit.com/r/funny`)
- Keyword/wildcard blocking (`google.com/*q=*unicorn*`)
- Block the entire internet (`*.*`) with per-list exceptions

### Application Blocking
- Block by `.exe` file
- Block by folder (all executables inside are blocked)
- Block Microsoft Store / UWP apps by AppUserModelID
- Block by window title substring

### Lock Methods
- Timer lock (until X)
- Random-text lock (1-999 chars)
- Time-range lock (only unlockable in a window, or blocked during one)
- Restart lock (requires full reboot to disarm)
- Password lock

### Advanced
- Block system time changes while a lock is active
- Block Task Manager while a lock is active
- Block embedded (iframe) content
- Command-line interface (`focusfortress start/stop/toggle/lock <block>`)

### Scheduling & Allowances
- Weekly click-and-drag schedule grid
- Allowances (foreground-only countdown with idle detection)
- Frozen Turkey (force lock / logoff / shutdown on schedule)
- Pomodoro cycles
- "Pause for a cause" (10 min break after donation prompt)

### Statistics
- Local-only tracking of time per site and per app
- Export to JSON, delete on demand

### Customization / System
- Custom block page (HTML or motivational quote)
- Per-Windows-user selection for each block
- OS-level enforcement (hosts file, local proxy, process enforcement)

## Requirements
- Windows 10 / 11
- Python 3.10+
- Admin privileges (the app will prompt for UAC elevation)

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python -m focusfortress
```

The app will relaunch itself elevated if it wasn't started as admin.

## CLI

```powershell
python -m focusfortress cli start "Work"
python -m focusfortress cli stop  "Work"
python -m focusfortress cli toggle "Work"
python -m focusfortress cli lock  "Work" --timer 02:00
```

## Packaging

```powershell
pip install pyinstaller
pyinstaller --noconfirm --windowed --name FocusFortress --uac-admin -i icon.ico focusfortress/__main__.py
```

## Data location

All settings and statistics are stored **locally** in
`%PROGRAMDATA%\FocusFortress\` (requires admin to edit).
No telemetry, no cloud, no accounts.

## Notes / Caveats

- Hosts-file blocking covers the vast majority of browser traffic. DNS-over-HTTPS in some browsers can bypass it; the bundled local proxy plus firewall rules close that gap for HTTP/S on ports 80/443.
- Kernel-mode enforcement (WFP) is outside the scope of a pure-Python MVP; we achieve comparable results with hosts + proxy + process watcher + task-manager policy.
- Blocking Task Manager uses the `DisableTaskMgr` policy, which requires admin.
- Time-change blocking uses the `SeSystemtimePrivilege` policy denial, which requires admin.
