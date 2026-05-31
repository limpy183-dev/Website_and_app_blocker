"""Configure FocusFortress to start automatically at Windows logon.

Uses a VBS launcher script + HKCU Run registry key (inspired by QuizGate).

The VBS script:
  - Waits 15 seconds for Windows services to initialise
  - Sets the correct working directory
  - Launches pythonw.exe -m focusfortress --background in a hidden window
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("focusfortress.autostart")

_TASK_NAME = "FocusFortress"
_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_REG_VALUE_NAME = "FocusFortress"


def _get_project_dir() -> str:
    """Return the root directory of the focusfortress package."""
    # focusfortress/ is the package dir; its parent is the project root.
    return str(Path(__file__).resolve().parent.parent)


def _get_python_exe() -> str:
    """Return the path to pythonw.exe (preferred) or python.exe."""
    exe = sys.executable
    exe_dir = os.path.dirname(exe)
    pythonw = os.path.join(exe_dir, "pythonw.exe")
    if os.path.isfile(pythonw):
        return pythonw
    return exe


def _get_vbs_path() -> Path:
    """Return the path where the VBS launcher script will be saved."""
    from .paths import DATA_DIR
    return DATA_DIR / "start_focusfortress.vbs"


def _write_vbs_launcher() -> Path:
    """Generate the VBS boot-launcher script and return its path."""
    vbs_path = _get_vbs_path()
    project_dir = _get_project_dir()
    python_exe = _get_python_exe()

    vbs_content = (
        "' FocusFortress Boot Launcher (auto-generated)\n"
        "Dim WshShell\n"
        'Set WshShell = CreateObject("WScript.Shell")\n'
        "WScript.Sleep 15000\n"
        f'WshShell.CurrentDirectory = "{project_dir}"\n'
        f'WshShell.Run """{python_exe}"" ""-m"" ""focusfortress"" ""--background""", 0, False\n'
        "Set WshShell = Nothing\n"
    )

    vbs_path.parent.mkdir(parents=True, exist_ok=True)
    vbs_path.write_text(vbs_content, encoding="utf-8")
    log.info("wrote VBS launcher: %s", vbs_path)
    return vbs_path


def _set_registry_run(vbs_path: Path) -> None:
    """Add an HKCU Run entry pointing to wscript.exe with the VBS launcher."""
    import winreg

    command = f'wscript.exe "{vbs_path}"'

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _REG_KEY,
        0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
    )
    try:
        winreg.SetValueEx(key, _REG_VALUE_NAME, 0, winreg.REG_SZ, command)
        log.info("set HKCU Run key: %s = %s", _REG_VALUE_NAME, command)

        # Verify the write
        stored, _ = winreg.QueryValueEx(key, _REG_VALUE_NAME)
        if stored != command:
            raise RuntimeError("registry verification failed: stored value doesn't match")
        log.info("verified HKCU Run key")
    finally:
        winreg.CloseKey(key)


def _remove_registry_run() -> None:
    """Delete the HKCU Run entry if it exists."""
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_KEY,
            0, winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, _REG_VALUE_NAME)
            log.info("removed HKCU Run key: %s", _REG_VALUE_NAME)
        except FileNotFoundError:
            pass  # already absent
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        log.debug("_remove_registry_run: %s", e)


def _remove_vbs_launcher() -> None:
    """Delete the VBS launcher file if it exists."""
    vbs_path = _get_vbs_path()
    if vbs_path.exists():
        try:
            vbs_path.unlink()
            log.info("removed VBS launcher: %s", vbs_path)
        except OSError as e:
            log.debug("failed to remove VBS: %s", e)


def _cleanup_legacy_schtask() -> None:
    """Remove the legacy scheduled task if it exists (old autostart approach)."""
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", _TASK_NAME],
            capture_output=True, text=True,
            creationflags=0x08000000,
        )
        if result.returncode == 0:
            subprocess.run(
                ["schtasks", "/Delete", "/TN", _TASK_NAME, "/F"],
                capture_output=True, text=True,
                creationflags=0x08000000,
            )
            log.info("removed legacy scheduled task '%s'", _TASK_NAME)
    except Exception as e:
        log.debug("legacy schtask cleanup: %s", e)


def _cleanup_old_registry() -> None:
    """Remove the legacy HKCU Run key if it was set by an even older approach."""
    # This is kept for back-compat; the new approach uses the same key name
    # so it will naturally overwrite any stale value.
    pass


# ---------- Public API ----------

def set_autostart(enabled: bool) -> None:
    """Enable or disable FocusFortress autostart at Windows logon."""
    # Always clean up the old schtasks approach.
    _cleanup_legacy_schtask()

    if enabled:
        try:
            vbs_path = _write_vbs_launcher()
            _set_registry_run(vbs_path)
        except Exception as e:
            log.error("failed to enable autostart: %s", e)
            raise
    else:
        _remove_registry_run()
        _remove_vbs_launcher()


def is_autostart_enabled() -> bool:
    """Check whether the autostart registry entry exists and is valid."""
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_KEY,
            0, winreg.KEY_QUERY_VALUE,
        )
        try:
            value, _ = winreg.QueryValueEx(key, _REG_VALUE_NAME)
            # Check that the VBS file it points to actually exists
            # Expected format: wscript.exe "C:\...\start_focusfortress.vbs"
            if "start_focusfortress.vbs" in value:
                vbs_path = _get_vbs_path()
                return vbs_path.exists()
            return False
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False
