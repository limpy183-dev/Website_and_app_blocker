"""Protect our own process from being terminated.

We modify the DACL of our own process so that ``PROCESS_TERMINATE`` (plus a few
related rights) is denied to "Everyone". Because a deny ACE for Everyone is
ordered ahead of any allow ACE in a canonical DACL, the effect is that
*everyone* — including SYSTEM and the current user — is denied
``PROCESS_TERMINATE``. (The SYSTEM allow entry we add below is therefore
effectively a no-op for the denied rights; we keep it documented so the intent
is clear, but it does NOT re-grant terminate to SYSTEM.) This is acceptable for
our threat model: we only need to stop the interactive user from killing the
process while a block is active, and we restore the default DACL in
``disable_kill_protection``.

Windows APIs used: ``GetCurrentProcess``, ``SetSecurityInfo`` with an ACL that
denies PROCESS_TERMINATE + PROCESS_VM_WRITE + PROCESS_CREATE_THREAD +
PROCESS_SUSPEND_RESUME.
"""
from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes

log = logging.getLogger("focusfortress.selfprotect")

# ---- Win32 constants ----

_PROCESS_TERMINATE = 0x0001
_PROCESS_CREATE_THREAD = 0x0002
_PROCESS_VM_WRITE = 0x0020
_PROCESS_SUSPEND_RESUME = 0x0800

_DACL_SECURITY_INFORMATION = 0x00000004
_SE_KERNEL_OBJECT = 6

_ACCESS_DENIED_ACE_TYPE = 0x01
_ACCESS_ALLOWED_ACE_TYPE = 0x00
_ACL_REVISION = 2

_NO_INHERITANCE = 0x0
_SET_ACCESS = 2
_DENY_ACCESS = 3
_GRANT_ACCESS = 1
_TRUSTEE_IS_SID = 0
_TRUSTEE_IS_WELL_KNOWN_GROUP = 5
_TRUSTEE_IS_USER = 1
_TRUSTEE_IS_GROUP = 2

_WinWorldSid = 1
_WinLocalSystemSid = 22


# Loaded lazily
_advapi32: ctypes.WinDLL | None = None
_kernel32: ctypes.WinDLL | None = None


def _libs() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    global _advapi32, _kernel32
    if _advapi32 is None:
        _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return _advapi32, _kernel32  # type: ignore[return-value]


# ---- Public API ----

_applied = False


def enable_kill_protection() -> bool:
    """Apply the self-protecting DACL. Returns True on success."""
    global _applied
    if _applied:
        return True
    try:
        advapi, kernel = _libs()

        # BuildExplicitAccessWithNameW + SetEntriesInAclW is the simplest path.
        # We'll use the higher-level SetSecurityInfo.

        class TRUSTEE_W(ctypes.Structure):
            _fields_ = [
                ("pMultipleTrustee", ctypes.c_void_p),
                ("MultipleTrusteeOperation", wintypes.DWORD),
                ("TrusteeForm", wintypes.DWORD),
                ("TrusteeType", wintypes.DWORD),
                ("ptstrName", wintypes.LPWSTR),
            ]

        class EXPLICIT_ACCESS_W(ctypes.Structure):
            _fields_ = [
                ("grfAccessPermissions", wintypes.DWORD),
                ("grfAccessMode", wintypes.DWORD),
                ("grfInheritance", wintypes.DWORD),
                ("Trustee", TRUSTEE_W),
            ]

        deny_mask = (
            _PROCESS_TERMINATE
            | _PROCESS_VM_WRITE
            | _PROCESS_CREATE_THREAD
            | _PROCESS_SUSPEND_RESUME
        )

        # Deny "Everyone"
        deny_everyone = EXPLICIT_ACCESS_W()
        deny_everyone.grfAccessPermissions = deny_mask
        deny_everyone.grfAccessMode = _DENY_ACCESS
        deny_everyone.grfInheritance = _NO_INHERITANCE
        deny_everyone.Trustee.TrusteeForm = 1  # TRUSTEE_IS_NAME
        deny_everyone.Trustee.TrusteeType = _TRUSTEE_IS_WELL_KNOWN_GROUP
        deny_everyone.Trustee.ptstrName = "Everyone"

        # Document an "allow SYSTEM full access" entry. NOTE: in a canonical
        # DACL the deny-Everyone ACE above is ordered first and supersedes this
        # allow for the denied rights, so SYSTEM is ALSO denied
        # PROCESS_TERMINATE. We keep the entry to make intent explicit; it is
        # effectively a no-op for the denied access mask. This is fine for our
        # threat model (we only need to block the interactive user).
        allow_system = EXPLICIT_ACCESS_W()
        allow_system.grfAccessPermissions = 0x001F0FFF  # PROCESS_ALL_ACCESS
        allow_system.grfAccessMode = _GRANT_ACCESS
        allow_system.grfInheritance = _NO_INHERITANCE
        allow_system.Trustee.TrusteeForm = 1  # TRUSTEE_IS_NAME
        allow_system.Trustee.TrusteeType = _TRUSTEE_IS_WELL_KNOWN_GROUP
        allow_system.Trustee.ptstrName = "SYSTEM"

        EAArray = EXPLICIT_ACCESS_W * 2
        entries = EAArray(deny_everyone, allow_system)

        new_acl = ctypes.c_void_p(0)
        advapi.SetEntriesInAclW.argtypes = [
            wintypes.ULONG, ctypes.POINTER(EXPLICIT_ACCESS_W),
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi.SetEntriesInAclW.restype = wintypes.DWORD
        rc = advapi.SetEntriesInAclW(2, entries, None, ctypes.byref(new_acl))
        if rc != 0:
            log.warning("SetEntriesInAclW failed: %s", rc)
            return False

        hproc = kernel.GetCurrentProcess()
        advapi.SetSecurityInfo.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        advapi.SetSecurityInfo.restype = wintypes.DWORD
        rc = advapi.SetSecurityInfo(
            hproc, _SE_KERNEL_OBJECT, _DACL_SECURITY_INFORMATION,
            None, None, new_acl, None,
        )
        if rc != 0:
            log.warning("SetSecurityInfo failed: %s", rc)
            return False

        _applied = True
        log.info("process kill-protection enabled")
        return True
    except Exception as e:
        log.warning("enable_kill_protection error: %s", e)
        return False


def disable_kill_protection() -> bool:
    """Restore the default DACL (allow everyone)."""
    global _applied
    try:
        advapi, kernel = _libs()
        hproc = kernel.GetCurrentProcess()
        # Passing a NULL DACL with DACL_SECURITY_INFORMATION set grants everyone access.
        advapi.SetSecurityInfo.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        advapi.SetSecurityInfo.restype = wintypes.DWORD
        advapi.SetSecurityInfo(hproc, _SE_KERNEL_OBJECT,
                               _DACL_SECURITY_INFORMATION,
                               None, None, None, None)
        _applied = False
        return True
    except Exception as e:
        log.debug("disable_kill_protection: %s", e)
        return False
