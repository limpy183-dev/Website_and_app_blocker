"""Advanced OS policies: block Task Manager and system time changes."""
from __future__ import annotations

import ctypes
import logging
import subprocess
import winreg

log = logging.getLogger("focusfortress.advanced")


_TASKMGR_KEY = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"


def set_task_manager_blocked(blocked: bool) -> None:
    """Write DisableTaskMgr policy (per-user)."""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _TASKMGR_KEY) as k:
            winreg.SetValueEx(k, "DisableTaskMgr", 0, winreg.REG_DWORD, 1 if blocked else 0)
    except Exception as e:
        log.debug("set_task_manager_blocked: %s", e)


def set_time_change_blocked(blocked: bool) -> None:
    """Remove/restore the SeSystemtimePrivilege from BUILTIN\\Users using secedit.

    Best-effort; on Home editions secedit may be absent.
    """
    if blocked:
        cmd = (
            'secedit /export /cfg "%TEMP%\\ff_sec.inf" >nul & '
            'findstr /v "SeSystemtimePrivilege" "%TEMP%\\ff_sec.inf" > "%TEMP%\\ff_sec2.inf" & '
            'echo SeSystemtimePrivilege = *S-1-5-32-544 >> "%TEMP%\\ff_sec2.inf" & '
            'secedit /configure /db "%TEMP%\\ff_sec.sdb" /cfg "%TEMP%\\ff_sec2.inf" /areas USER_RIGHTS >nul'
        )
    else:
        cmd = (
            'secedit /export /cfg "%TEMP%\\ff_sec.inf" >nul & '
            'findstr /v "SeSystemtimePrivilege" "%TEMP%\\ff_sec.inf" > "%TEMP%\\ff_sec2.inf" & '
            'echo SeSystemtimePrivilege = *S-1-5-32-544,*S-1-5-19,*S-1-5-32-545 >> "%TEMP%\\ff_sec2.inf" & '
            'secedit /configure /db "%TEMP%\\ff_sec.sdb" /cfg "%TEMP%\\ff_sec2.inf" /areas USER_RIGHTS >nul'
        )
    try:
        subprocess.run(["cmd", "/c", cmd], check=False, capture_output=True,
                       creationflags=0x08000000)
    except Exception as e:
        log.debug("set_time_change_blocked: %s", e)


def reload_policy() -> None:
    try:
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF, 0x001A, 0, "Policy", 0x0002, 5000, None
        )
    except Exception:
        pass
