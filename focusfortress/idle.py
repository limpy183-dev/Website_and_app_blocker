"""Idle-time detection via Windows GetLastInputInfo."""
from __future__ import annotations

import ctypes
from ctypes import wintypes


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds() -> float:
    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        # GetTickCount returns an *unsigned* 32-bit millisecond counter that
        # wraps every ~49.7 days.  With the default (signed) ctypes restype it
        # would also read back as negative after ~24.8 days.  Force an unsigned
        # DWORD restype and compute the delta in 32-bit space so the wrap is
        # handled correctly (dwTime is itself a 32-bit DWORD).
        kernel32 = ctypes.windll.kernel32
        kernel32.GetTickCount.restype = wintypes.DWORD
        now32 = kernel32.GetTickCount()
        delta = (now32 - lii.dwTime) & 0xFFFFFFFF
        return max(0.0, delta / 1000.0)
    except Exception:
        return 0.0
