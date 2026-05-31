"""UAC elevation helper. Re-launches the current process as administrator."""
from __future__ import annotations

import ctypes
import os
import sys


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ensure_admin() -> None:
    """If not running elevated, relaunch ourselves via ShellExecute 'runas' and exit."""
    if os.environ.get("FOCUSFORTRESS_NO_ELEVATE") == "1":
        return
    if is_admin():
        return

    # Build the command line for the elevated copy.
    exe = sys.executable
    # Prefer pythonw.exe to avoid a visible CMD window.
    exe_dir = os.path.dirname(exe)
    pythonw = os.path.join(exe_dir, "pythonw.exe")
    if os.path.isfile(pythonw):
        exe = pythonw

    argv = list(sys.argv)
    
    # If launched via `python -m focusfortress`, `sys.argv[0]` is the absolute path to __main__.py.
    # We must relaunch with `-m` to avoid ImportErrors regarding relative imports.
    main_mod = sys.modules.get("__main__")
    pkg = getattr(main_mod, "__package__", None)
    if pkg:
        argv.pop(0)
        argv.insert(0, pkg)
        argv.insert(0, "-m")
        
    params = " ".join(f'"{a}"' for a in argv)

    # SW_HIDE = 0  (no console window)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 0)
    if rc <= 32:
        # User declined or error - we can still run with limited capabilities.
        print(
            "FocusFortress needs administrator privileges for OS-level blocking.\n"
            "Continuing with reduced functionality.",
            file=sys.stderr,
        )
        return
    sys.exit(0)

