"""Watchdog helper process(es).

Two modes are supported:

* **Normal mode** (`start_watchdog`): a single detached child polls every
  2 s and only respawns the main process if it dies *while a block is
  enabled*.

* **Force-protect mode** (`start_force_protect_watchdog`): a pair of
  detached children that watch (a) the main process, and (b) each other.
  Polling is bumped to 0.5 s and the main process is respawned
  unconditionally - blocks do not have to be enabled.  Killing one
  watchdog is futile because its partner immediately relaunches it.

The watchdog quits gracefully if the *state file* marks
``watchdog_should_exit`` AND we are not in force-protect mode (force-
protect mode also requires ``force_protect_enabled`` to be flipped off).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from typing import Optional

import psutil

from .config_store import load_state, save_state
from .paths import DATA_DIR

log = logging.getLogger("focusfortress.watchdog")


_WATCHDOG_MARK = DATA_DIR / "watchdog.pid"
# Force-protect uses two PID files (role A + role B) so each watchdog
# can find its partner.
_FORCE_A_PID_FILE = DATA_DIR / "watchdog.A.pid"
_FORCE_B_PID_FILE = DATA_DIR / "watchdog.B.pid"

_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    try:
        return bool(pid) and psutil.pid_exists(int(pid))
    except Exception:
        return False


def _read_pid(path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def _write_pid(path, pid: int) -> None:
    try:
        path.write_text(str(pid), encoding="utf-8")
    except Exception:
        pass


def _spawn(args: list[str]) -> Optional[subprocess.Popen]:
    try:
        return subprocess.Popen(args, creationflags=_DETACHED, close_fds=True)
    except Exception as e:
        log.debug("watchdog spawn failed: %s", e)
        return None


def _find_running_focusfortress(exclude_pid: int = 0) -> int:
    """Return the PID of the running main FocusFortress GUI, or 0.

    We exclude watchdog and CLI sub-processes by inspecting cmdline.
    """
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            if p.info["pid"] == exclude_pid:
                continue
            cmd = " ".join(str(c) for c in (p.info.get("cmdline") or [])).lower()
            if "focusfortress" not in cmd:
                continue
            if "watchdog" in cmd or " cli" in cmd or cmd.endswith("cli"):
                continue
            return int(p.info["pid"])
        except Exception:
            continue
    return 0


# ===========================================================================
# Normal watchdog
# ===========================================================================

def start_watchdog() -> None:
    """Spawn a single, on-demand watchdog (normal mode)."""
    if _watchdog_alive():
        return
    state = load_state()
    state["watchdog_should_exit"] = False
    state["main_pid"] = os.getpid()
    save_state(state)
    _spawn([sys.executable, "-m", "focusfortress", "watchdog", str(os.getpid())])


def stop_watchdog() -> None:
    """Ask the normal watchdog to exit gracefully."""
    state = load_state()
    state["watchdog_should_exit"] = True
    save_state(state)


def _watchdog_alive() -> bool:
    return _pid_alive(_read_pid(_WATCHDOG_MARK))


def run_watchdog(main_pid: int) -> int:
    """Entry point for the *normal* watchdog process."""
    _write_pid(_WATCHDOG_MARK, os.getpid())
    restart_cmd = [sys.executable, "-m", "focusfortress"]

    while True:
        time.sleep(2.0)
        state = load_state()
        if state.get("watchdog_should_exit"):
            break

        # Only relaunch if a block is currently enabled.
        try:
            cfg_path = DATA_DIR / "config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            any_enabled = any(b.get("enabled") for b in cfg.get("blocks", []))
        except Exception:
            any_enabled = False
        if not any_enabled:
            continue

        tracked = state.get("main_pid", main_pid)
        if tracked and _pid_alive(int(tracked)):
            continue

        # See if it's been restarted under a fresh PID.
        found = _find_running_focusfortress(exclude_pid=os.getpid())
        if found:
            state["main_pid"] = found
            save_state(state)
            continue

        _spawn(restart_cmd)

    try:
        _WATCHDOG_MARK.unlink(missing_ok=True)
    except Exception:
        pass
    return 0


# ===========================================================================
# Force-protect watchdogs (paired, fast-poll, always-on)
# ===========================================================================

_FORCE_POLL_SECONDS = 0.5


def _other_role(role: str) -> str:
    return "B" if role == "A" else "A"


def _role_pid_file(role: str):
    return _FORCE_A_PID_FILE if role == "A" else _FORCE_B_PID_FILE


def start_force_protect_watchdog() -> None:
    """Ensure BOTH role-A and role-B partner watchdogs are running.

    Idempotent: if either is already alive we leave it; if either is
    missing we (re)spawn it.
    """
    state = load_state()
    state["force_protect_enabled"] = True
    state["main_pid"] = os.getpid()
    save_state(state)

    for role in ("A", "B"):
        if _pid_alive(_read_pid(_role_pid_file(role))):
            continue
        _spawn([sys.executable, "-m", "focusfortress",
                "watchdog", str(os.getpid()), "--force", "--role", role])


def stop_force_protect_watchdog() -> None:
    """Signal both partner watchdogs to exit and clear their PID files."""
    state = load_state()
    state["force_protect_enabled"] = False
    state["watchdog_should_exit"] = True  # also stops the normal one
    save_state(state)
    # Don't try to kill them - the DACL might forbid it.  Just let the
    # next poll see the flag and return cleanly.


def run_force_protect_watchdog(main_pid: int, role: str) -> int:
    """Entry point for one half of the force-protect pair.

    The watchdog watches:
      * the main FocusFortress process - relaunch on death
      * its partner watchdog - relaunch on death
    """
    role = "B" if role == "B" else "A"
    partner = _other_role(role)

    pid_file = _role_pid_file(role)
    _write_pid(pid_file, os.getpid())

    restart_cmd = [sys.executable, "-m", "focusfortress"]
    main_args = [sys.executable, "-m", "focusfortress", "--background"]

    while True:
        time.sleep(_FORCE_POLL_SECONDS)
        state = load_state()
        if not state.get("force_protect_enabled"):
            break

        # 1) Watch the main process.
        tracked = int(state.get("main_pid") or main_pid or 0)
        if not _pid_alive(tracked):
            found = _find_running_focusfortress(exclude_pid=os.getpid())
            if found:
                state["main_pid"] = found
                save_state(state)
            else:
                # Relaunch in background mode so we don't pop a window.
                if _spawn(main_args):
                    log.info("force-protect[%s]: relaunched main process", role)

        # 2) Watch the partner watchdog.
        p_pid = _read_pid(_role_pid_file(partner))
        if not _pid_alive(p_pid):
            _spawn([sys.executable, "-m", "focusfortress",
                    "watchdog", str(state.get("main_pid", main_pid)),
                    "--force", "--role", partner])
            log.info("force-protect[%s]: relaunched partner %s", role, partner)

    try:
        pid_file.unlink(missing_ok=True)
    except Exception:
        pass
    return 0
