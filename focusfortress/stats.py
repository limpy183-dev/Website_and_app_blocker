"""Foreground tracker: records seconds spent per app and browsed site.

Site tracking works in two complementary ways:

1. Whenever a browser is the foreground window we sample its title and try to
   extract a domain-like substring. This is approximate but needs no proxy.

2. Every request the local proxy sees is reported via a callback so we can
   attribute **real** browsing time to hostnames. This works whether the site
   is on a blocklist or not: any site whose traffic transits the proxy is
   tracked. (Sites blocked at the hosts-file level never reach the proxy, so
   the foreground-title heuristic is what catches those attempts.)
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import threading
import time
from pathlib import Path
from typing import Optional

import psutil

from .blocking.proxy import set_site_observer
from .config_store import load_stats, save_stats

log = logging.getLogger("focusfortress.stats")

try:
    import win32gui      # type: ignore
    import win32process  # type: ignore
    _HAVE_WIN32 = True
except Exception:
    _HAVE_WIN32 = False


_BROWSERS = {
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe",
}


def _get_foreground_info() -> tuple[str, str] | None:
    if not _HAVE_WIN32:
        return None
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            p = psutil.Process(pid)
            name = p.name()
        except Exception:
            name = ""
        return name.lower(), title
    except Exception:
        return None


_URL_IN_TITLE = re.compile(r"[\w.-]+\.[a-z]{2,}", re.IGNORECASE)


def _extract_site_from_title(title: str) -> Optional[str]:
    # Browser window titles like "Page Name - Google Chrome" often don't contain URLs.
    # This is best-effort: match any domain-like substring.
    m = _URL_IN_TITLE.search(title)
    if m:
        return m.group(0).lower()
    return None


class StatsTracker:
    def __init__(self, poll_seconds: float = 5.0) -> None:
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Aggregate proxy-observed site hits between flushes.
        self._proxy_hits: dict[str, int] = {}
        self._proxy_lock = threading.Lock()

    # Called by the proxy on every request it sees.
    def _on_proxy_request(self, host: str, blocked: bool) -> None:
        # Collapse www/m prefixes so stats group sensibly.
        h = host.lower()
        for pref in ("www.", "m.", "mobile."):
            if h.startswith(pref):
                h = h[len(pref):]
                break
        # Count each request as a 2-second "visit" (very rough, but only used
        # when a browser doesn't expose its URL in the title).
        with self._proxy_lock:
            self._proxy_hits[h] = self._proxy_hits.get(h, 0) + 2

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        set_site_observer(self._on_proxy_request)
        self._thread = threading.Thread(target=self._run, name="ff-stats", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        set_site_observer(None)
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                log.debug("stats tick error: %s", e)
            self._stop.wait(self.poll_seconds)

    def _tick(self) -> None:
        info = _get_foreground_info()
        if not info:
            return
        proc_name, title = info
        stats = load_stats()
        today = dt.date.today().isoformat()
        stats.setdefault("days", {}).setdefault(today, {"sites": {}, "apps": {}})
        stats.setdefault("sites", {})
        stats.setdefault("apps", {})

        if proc_name:
            stats["apps"][proc_name] = stats["apps"].get(proc_name, 0) + self.poll_seconds
            stats["days"][today]["apps"][proc_name] = (
                stats["days"][today]["apps"].get(proc_name, 0) + self.poll_seconds
            )

        if proc_name in _BROWSERS:
            site = _extract_site_from_title(title)
            if site:
                stats["sites"][site] = stats["sites"].get(site, 0) + self.poll_seconds
                stats["days"][today]["sites"][site] = (
                    stats["days"][today]["sites"].get(site, 0) + self.poll_seconds
                )

        # Flush any proxy-observed sites collected since the last tick.
        with self._proxy_lock:
            hits = self._proxy_hits
            self._proxy_hits = {}
        for host, secs in hits.items():
            stats["sites"][host] = stats["sites"].get(host, 0) + secs
            stats["days"][today]["sites"][host] = (
                stats["days"][today]["sites"].get(host, 0) + secs
            )

        save_stats(stats)
