"""Strongest available "Force Protect from Termination" mode.

This module orchestrates *every* realistic Windows-userspace defence we
can stack on a non-driver, non-service install:

1. **DACL deny** on PROCESS_TERMINATE / VM_WRITE / CREATE_THREAD /
   SUSPEND_RESUME for our own process.  This is what blocks
   ``taskkill`` and Task Manager's "End task" outright.

2. **Console-signal handler** that swallows CTRL+C, CTRL+BREAK,
   CTRL+CLOSE, CTRL+LOGOFF and CTRL+SHUTDOWN so console-based or
   shell-based termination paths cannot exit us either.

3. **Process priority bump** to HIGH so the process can't be starved by
   a runaway background task and is harder to "freeze" via priority
   manipulation.

4. **Always-on, fast-poll watchdog**.  In normal mode the watchdog only
   polls every 2 s and only cares while a block is enabled.  Force-
   protect mode bumps the poll rate to 0.5 s and keeps the watchdog
   active *unconditionally* - even if every block is disabled.

5. **Mutual / partner watchdogs.**  Two watchdog processes are spawned.
   Each polls (a) the main process and (b) its partner.  Killing one
   watchdog is futile - the other relaunches it within a second.  The
   main process also re-checks both watchdogs are alive every tick and
   respawns any that have died.

This module is a no-op on non-Windows hosts so the codebase still
imports cleanly during tests.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Optional

from . import selfprotect
from . import watchdog as _watchdog

log = logging.getLogger("focusfortress.force_protect")


_console_handler_installed = False
_priority_set = False
_active = False


# ---------------------------------------------------------------------------
# Console-signal swallowing
# ---------------------------------------------------------------------------

def _install_console_handler() -> None:
    """Register a Win32 console-control handler that returns TRUE for
    every signal so the OS does not propagate the request."""
    global _console_handler_installed
    if _console_handler_installed:
        return
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        from ctypes import wintypes

        HANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        def _handler(ctrl_type):  # noqa: ANN001
            # 0=CTRL_C, 1=CTRL_BREAK, 2=CTRL_CLOSE, 5=CTRL_LOGOFF, 6=CTRL_SHUTDOWN
            log.info("force_protect: swallowed console signal %s", ctrl_type)
            return True  # handled - do NOT terminate

        # We must keep a strong ref or the callback will be GC'd.
        global _handler_ref
        _handler_ref = HANDLER_ROUTINE(_handler)  # type: ignore[name-defined]
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetConsoleCtrlHandler.argtypes = [HANDLER_ROUTINE, wintypes.BOOL]
        kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL
        if kernel32.SetConsoleCtrlHandler(_handler_ref, True):
            _console_handler_installed = True
            log.debug("force_protect: console-control handler installed")
    except Exception as e:
        log.debug("force_protect: install_console_handler failed: %s", e)


# ---------------------------------------------------------------------------
# Process-priority bump
# ---------------------------------------------------------------------------

def _bump_priority() -> None:
    global _priority_set
    if _priority_set:
        return
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # HIGH_PRIORITY_CLASS = 0x00000080
        if kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x00000080):
            _priority_set = True
            log.debug("force_protect: priority -> HIGH")
    except Exception as e:
        log.debug("force_protect: bump_priority failed: %s", e)


def _restore_priority() -> None:
    global _priority_set
    if not _priority_set:
        return
    if not sys.platform.startswith("win"):
        _priority_set = False
        return
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # NORMAL_PRIORITY_CLASS = 0x00000020
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x00000020)
    except Exception:
        pass
    _priority_set = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_active() -> bool:
    return _active


def enable() -> None:
    """Engage every layer of force-protection.  Idempotent."""
    global _active
    if _active:
        # Re-arm the watchdog anyway in case it died between calls.
        _watchdog.start_force_protect_watchdog()
        return

    # Layer 1 - DACL deny
    try:
        selfprotect.enable_kill_protection()
    except Exception as e:
        log.debug("force_protect: enable_kill_protection failed: %s", e)

    # Layer 2 - swallow console signals
    _install_console_handler()

    # Layer 3 - HIGH priority
    _bump_priority()

    # Layer 4+5 - always-on, partner-watched watchdog
    try:
        _watchdog.start_force_protect_watchdog()
    except Exception as e:
        log.warning("force_protect: watchdog startup failed: %s", e)

    _active = True
    log.info("force_protect: ENABLED (DACL + console + priority + dual watchdog)")


def disable() -> None:
    """Tear down force-protection layers and restore normal behaviour."""
    global _active
    if not _active:
        return
    try:
        selfprotect.disable_kill_protection()
    except Exception:
        pass
    _restore_priority()
    try:
        _watchdog.stop_force_protect_watchdog()
    except Exception:
        pass
    _active = False
    log.info("force_protect: disabled")


def reassert() -> None:
    """Best-effort re-application of all layers.  The engine calls this
    every tick so even if some layer is somehow stripped (e.g. priority
    reset by an admin tool) it is restored within ~10 s."""
    if not _active:
        return
    try:
        selfprotect.enable_kill_protection()
    except Exception:
        pass
    _bump_priority()
    try:
        _watchdog.start_force_protect_watchdog()  # idempotent
    except Exception:
        pass
