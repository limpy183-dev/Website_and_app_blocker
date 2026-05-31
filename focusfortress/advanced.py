"""Advanced OS policies: block Task Manager and system time changes."""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile

try:  # Windows-only modules; guarded so the module imports cross-platform.
    import ctypes
    import winreg
except Exception:  # pragma: no cover - non-Windows
    ctypes = None  # type: ignore[assignment]
    winreg = None  # type: ignore[assignment]

from .config_store import load_state, save_state

log = logging.getLogger("focusfortress.advanced")


_TASKMGR_KEY = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"

# Administrators-only assignment we apply while blocking time changes.
_BLOCK_PRIVILEGE_RHS = "*S-1-5-32-544"
# Persisted-state key holding the machine's ORIGINAL SeSystemtimePrivilege RHS.
_ORIG_PRIV_KEY = "original_systemtime_privilege"
# Cache of the last state we actually applied, so we don't re-run secedit every
# ~10s tick.  Process-scoped (the persisted snapshot covers correctness across
# restarts).
_last_time_block_state = None


def set_task_manager_blocked(blocked: bool) -> None:
    """Write DisableTaskMgr policy (per-user)."""
    if os.name != "nt" or winreg is None:
        return
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _TASKMGR_KEY) as k:
            winreg.SetValueEx(k, "DisableTaskMgr", 0, winreg.REG_DWORD, 1 if blocked else 0)
    except Exception as e:
        log.debug("set_task_manager_blocked: %s", e)


# ---------------------------------------------------------------------------
# System-time-change blocking via secedit
# ---------------------------------------------------------------------------

def _export_systemtime_privilege() -> str | None:
    """Dump the current security policy and return the RHS of the
    ``SeSystemtimePrivilege`` line (under ``[Privilege Rights]``), or ``None``
    if it cannot be determined.

    Returns "" (empty string) if the privilege is explicitly assigned to nobody
    but the export succeeded; ``None`` only when we genuinely could not read it.
    """
    if os.name != "nt":
        return None
    inf_path = os.path.join(tempfile.gettempdir(), "ff_sec_export.inf")
    try:
        try:
            os.remove(inf_path)
        except OSError:
            pass
        subprocess.run(
            ["secedit", "/export", "/cfg", inf_path, "/areas", "USER_RIGHTS"],
            check=False, capture_output=True, creationflags=0x08000000,
        )
        if not os.path.exists(inf_path):
            return None
        text = None
        for enc in ("utf-16", "utf-8", "latin-1"):
            try:
                with open(inf_path, "r", encoding=enc) as fh:
                    text = fh.read()
                break
            except (UnicodeError, OSError):
                continue
        if text is None:
            return None
        for raw in text.splitlines():
            line = raw.strip()
            if line.lower().startswith("sesystemtimeprivilege"):
                # Form: "SeSystemtimePrivilege = *S-1-5-32-544,*S-1-5-19"
                _, _, rhs = line.partition("=")
                return rhs.strip()
        # The privilege line is absent -> the policy assigns it to no one.
        return ""
    except Exception as e:
        log.debug("_export_systemtime_privilege: %s", e)
        return None
    finally:
        try:
            os.remove(inf_path)
        except OSError:
            pass


def _apply_systemtime_privilege(rhs: str) -> None:
    """Write ``SeSystemtimePrivilege = <rhs>`` into the policy via secedit."""
    if os.name != "nt":
        return
    tmp = tempfile.gettempdir()
    inf_path = os.path.join(tmp, "ff_sec_apply.inf")
    sdb_path = os.path.join(tmp, "ff_sec_apply.sdb")
    try:
        content = (
            "[Unicode]\r\n"
            "Unicode=yes\r\n"
            "[Version]\r\n"
            "signature=\"$CHICAGO$\"\r\n"
            "Revision=1\r\n"
            "[Privilege Rights]\r\n"
            f"SeSystemtimePrivilege = {rhs}\r\n"
        )
        # secedit reads UTF-16 INF files.
        with open(inf_path, "w", encoding="utf-16") as fh:
            fh.write(content)
        subprocess.run(
            ["secedit", "/configure", "/db", sdb_path, "/cfg", inf_path,
             "/areas", "USER_RIGHTS"],
            check=False, capture_output=True, creationflags=0x08000000,
        )
    except Exception as e:
        log.debug("_apply_systemtime_privilege: %s", e)
    finally:
        for p in (inf_path, sdb_path):
            try:
                os.remove(p)
            except OSError:
                pass


def set_time_change_blocked(blocked: bool) -> None:
    """Block/restore the SeSystemtimePrivilege via secedit.

    Blocking restricts the privilege to Administrators only; unblocking
    restores EXACTLY the assignment the machine had the first time we blocked
    (captured and persisted), rather than hardcoding a guessed set.

    Only runs secedit on an actual state change (cached in
    ``_last_time_block_state``) - the engine calls this every ~10s and we must
    not re-run secedit constantly.  Best-effort / fail-soft: on Home editions
    secedit may be absent, and the whole thing is guarded for non-Windows so
    the test suite can import and call it safely.
    """
    global _last_time_block_state

    if os.name != "nt":
        return
    if blocked == _last_time_block_state:
        return  # no change since last apply - skip the expensive secedit run

    try:
        if blocked:
            # Capture the TRUE original once, before our first modification.
            state = load_state()
            if _ORIG_PRIV_KEY not in state:
                original = _export_systemtime_privilege()
                if original is not None:
                    state[_ORIG_PRIV_KEY] = original
                    save_state(state)
            _apply_systemtime_privilege(_BLOCK_PRIVILEGE_RHS)
        else:
            state = load_state()
            if _ORIG_PRIV_KEY in state:
                original = state.get(_ORIG_PRIV_KEY)
                # Restore exactly what we captured (verbatim, even if "").
                _apply_systemtime_privilege(original if original is not None else "")
                state.pop(_ORIG_PRIV_KEY, None)
                save_state(state)
            # If we never captured an original there is nothing to restore -
            # leave the policy as-is rather than hardcoding a guess.
        _last_time_block_state = blocked
    except Exception as e:
        log.debug("set_time_change_blocked: %s", e)


def reload_policy() -> None:
    if os.name != "nt" or ctypes is None:
        return
    try:
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF, 0x001A, 0, "Policy", 0x0002, 5000, None
        )
    except Exception:
        pass
