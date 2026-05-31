"""Application-level blocking: processes, folders, window titles, UWP apps."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Iterable, List, Set

import psutil

log = logging.getLogger("focusfortress.apps")


try:
    import win32gui     # type: ignore
    import win32process  # type: ignore
    _HAVE_WIN32 = True
except Exception:
    _HAVE_WIN32 = False


def _norm(p: str) -> str:
    try:
        return str(Path(p).resolve()).lower()
    except Exception:
        return p.lower()


class AppBlocker:
    """Background watcher that terminates processes matching rule-set."""

    def __init__(self, poll_seconds: float = 1.0) -> None:
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._exe_paths: Set[str] = set()
        self._folders: List[str] = []
        self._window_titles: List[str] = []
        self._store_apps: List[str] = []

    # ---- rule set ----

    def set_rules(
        self,
        exe_paths: Iterable[str],
        folders: Iterable[str],
        window_titles: Iterable[str],
        store_apps: Iterable[str],
    ) -> None:
        self._exe_paths = {_norm(p) for p in exe_paths if p}
        self._folders = [_norm(p) for p in folders if p]
        self._window_titles = [t.strip().lower() for t in window_titles if t.strip()]
        self._store_apps = [s.strip().lower() for s in store_apps if s.strip()]

    # ---- lifecycle ----

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ff-apps", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ---- main loop ----

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                log.debug("app tick error: %s", e)
            self._stop.wait(self.poll_seconds)

    def _tick(self) -> None:
        kill_pids: Set[int] = set()

        # 1. Process & folder matches
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                exe = proc.info.get("exe")
                if not exe:
                    continue
                norm = _norm(exe)
                if norm in self._exe_paths:
                    kill_pids.add(proc.info["pid"])
                    continue
                for folder in self._folders:
                    if norm.startswith(folder.rstrip("\\/") + os.sep) or norm.startswith(folder.rstrip("\\/") + "/"):
                        kill_pids.add(proc.info["pid"])
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # 2. Window-title matches (and UWP: we kill the owner PID)
        if _HAVE_WIN32 and (self._window_titles or self._store_apps):
            def cb(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                try:
                    title = win32gui.GetWindowText(hwnd) or ""
                except Exception:
                    return True
                title_l = title.lower()
                matched = False
                for needle in self._window_titles:
                    if needle and needle in title_l:
                        matched = True
                        break
                if not matched:
                    for app in self._store_apps:
                        if app and app in title_l:
                            matched = True
                            break
                if matched:
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        kill_pids.add(pid)
                    except Exception:
                        pass
                return True
            try:
                win32gui.EnumWindows(cb, None)
            except Exception:
                pass

        # 3. Store apps by package-family name: use `Get-StartApps` list we passed in
        #    and shutdown the associated process if the AUMID appears among running apps.
        if self._store_apps:
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                except Exception:
                    continue
                for app in self._store_apps:
                    # Best-effort: a package family name often contains something recognisable
                    # (e.g. "Microsoft.ZuneMusic_8wekyb3d8bbwe" -> zunemusic).
                    core = app.split("_", 1)[0].split(".")[-1].lower()
                    if core and core in name:
                        kill_pids.add(proc.info["pid"])
                        break

        # 4. Actually kill
        for pid in kill_pids:
            try:
                p = psutil.Process(pid)
                p.kill()
                log.info("killed blocked process pid=%s name=%s", pid, p.name())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue


def list_store_apps() -> List[str]:
    """Return UWP AppUserModelIDs using PowerShell (best-effort)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-StartApps | Select-Object -ExpandProperty AppID"],
            capture_output=True, text=True, timeout=15,
            creationflags=0x08000000,
        )
        return [l.strip() for l in out.stdout.splitlines() if l.strip()]
    except Exception:
        return []
