"""Configure the Windows (WinINET) proxy so that browsers use our local proxy."""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

import winreg

log = logging.getLogger("focusfortress.winproxy")


_INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

_INTERNET_OPTION_SETTINGS_CHANGED = 39
_INTERNET_OPTION_REFRESH = 37


# Default ProxyOverride entries. We always want loopback / link-local
# traffic to skip the proxy entirely so local apps (dev servers, electron
# apps talking to localhost helpers, printers, etc.) keep working.
#
#   <-loopback>  modern Windows token covering 127.0.0.0/8, ::1, localhost
#   <local>      bypasses simple hostnames (no dots) - intranet machines
#
# We also list the literal IPv4/IPv6 loopbacks so older Windows builds that
# don't honour <-loopback> still bypass them.
_DEFAULT_BYPASS = "127.0.0.1;localhost;[::1];<-loopback>;<local>"


def _refresh() -> None:
    try:
        wininet = ctypes.windll.wininet
        wininet.InternetSetOptionW(0, _INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        wininet.InternetSetOptionW(0, _INTERNET_OPTION_REFRESH, 0, 0)
    except Exception as e:
        log.debug("InternetSetOption failed: %s", e)


def enable_proxy(
    host: str = "127.0.0.1",
    port: int = 58123,
    bypass: str | None = None,
) -> None:
    """Enable the WinINET proxy and install a generous bypass list.

    ``bypass`` may be passed explicitly to extend the defaults; anything the
    caller supplies is appended to (not replacing) the loopback bypass set
    so local services stay reachable in every configuration.
    """
    server = f"{host}:{port}"
    if bypass and bypass.strip():
        # De-dup while preserving order.
        seen: set[str] = set()
        merged: list[str] = []
        for token in (_DEFAULT_BYPASS + ";" + bypass).split(";"):
            t = token.strip()
            if not t or t.lower() in seen:
                continue
            seen.add(t.lower())
            merged.append(t)
        bypass_value = ";".join(merged)
    else:
        bypass_value = _DEFAULT_BYPASS
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INTERNET_SETTINGS, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, server)
        winreg.SetValueEx(k, "ProxyOverride", 0, winreg.REG_SZ, bypass_value)
    _refresh()


def disable_proxy() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INTERNET_SETTINGS, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 0)
    except Exception as e:
        log.debug("disable_proxy: %s", e)
    _refresh()


def read_proxy() -> tuple[bool, str, str]:
    """Return (enabled, server, bypass) from the current WinINET config."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INTERNET_SETTINGS) as k:
            enabled, _ = winreg.QueryValueEx(k, "ProxyEnable")
            try:
                server, _ = winreg.QueryValueEx(k, "ProxyServer")
            except FileNotFoundError:
                server = ""
            try:
                bypass, _ = winreg.QueryValueEx(k, "ProxyOverride")
            except FileNotFoundError:
                bypass = ""
            return bool(enabled), str(server), str(bypass)
    except Exception:
        return False, "", ""
