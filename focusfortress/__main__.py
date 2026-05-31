"""Entry point: `python -m focusfortress` or PyInstaller target."""
import os
import sys

from .elevation import ensure_admin
from .paths import ensure_data_dirs


def _kill_other_instances() -> None:
    """Terminate any other FocusFortress GUI/background processes (not cli/watchdog)."""
    import psutil
    my_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.info["pid"] == my_pid:
                continue
            cmdline = proc.info.get("cmdline") or []
            cmd_str = " ".join(str(c) for c in cmdline).lower()
            # Match focusfortress but skip watchdog and cli sub-processes.
            if "focusfortress" in cmd_str and "watchdog" not in cmd_str and "cli" not in cmd_str:
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
            continue


def main() -> int:
    # First positional arg "cli" -> command line interface, no GUI.
    if len(sys.argv) >= 2 and sys.argv[1] == "cli":
        from .cli import run_cli

        ensure_admin()
        ensure_data_dirs()
        return run_cli(sys.argv[2:])

    # Watchdog mode (invoked by main process). No GUI, no elevation dance.
    if len(sys.argv) >= 2 and sys.argv[1] == "watchdog":
        from .watchdog import run_watchdog, run_force_protect_watchdog
        ensure_data_dirs()
        try:
            pid = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        except ValueError:
            pid = 0
        # Force-protect partner mode: `watchdog <pid> --force --role A|B`
        if "--force" in sys.argv:
            role = "A"
            if "--role" in sys.argv:
                try:
                    role = sys.argv[sys.argv.index("--role") + 1]
                except IndexError:
                    role = "A"
            return run_force_protect_watchdog(pid, role)
        return run_watchdog(pid)

    # Check for --background flag (start in tray, no window).
    background = "--background" in sys.argv

    ensure_admin()
    ensure_data_dirs()

    # Kill any existing FocusFortress GUI instances so only one runs at a time.
    _kill_other_instances()

    from .ui.app import run_gui

    return run_gui(background=background)


if __name__ == "__main__":
    sys.exit(main())
