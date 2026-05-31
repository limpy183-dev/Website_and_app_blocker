"""Manage the Windows hosts file for domain-level blocking."""
from __future__ import annotations

import os
import re
import stat
import tempfile
from typing import Iterable, List

from ..paths import HOSTS_FILE, HOSTS_MARK_BEGIN, HOSTS_MARK_END


REDIRECT_IP = "127.0.0.1"


def _extract_domain(pattern: str) -> str | None:
    """Return a bare domain suitable for hosts file, or None if not representable."""
    p = pattern.strip().lower()
    if not p:
        return None
    if p == "*.*":
        # Block-the-internet is handled elsewhere; we never write * to hosts.
        return None
    # Strip scheme
    p = re.sub(r"^[a-z]+://", "", p)
    # Take up to first / or ?
    p = re.split(r"[/?#]", p, maxsplit=1)[0]
    # Reject wildcards in the hostname - these go to the proxy path-matcher only
    if "*" in p:
        return None
    # Strip leading dots, then a leading "www." so we don't later re-expand it
    # into "www.www.x.com" (and so "www.x.com" and "x.com" collapse to one
    # canonical domain that _expand_variants re-adds the www. form for).
    p = p.lstrip(".")
    if p.startswith("www."):
        p = p[len("www."):]
    return p or None


def _expand_variants(domain: str) -> List[str]:
    variants = {domain, f"www.{domain}", f"m.{domain}", f"mobile.{domain}"}
    # Also common CDN/api subdomains for popular sites (best-effort).
    common = ["cdn", "api", "static", "img"]
    for c in common:
        variants.add(f"{c}.{domain}")
    return sorted(variants)


def read_hosts() -> str:
    try:
        return HOSTS_FILE.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def write_block_section(domains: Iterable[str]) -> None:
    """Replace the FocusFortress-managed block between the two marker lines."""
    current = read_hosts()
    pre, _, rest = current.partition(HOSTS_MARK_BEGIN)
    if HOSTS_MARK_BEGIN in current:
        _, _, after_end = rest.partition(HOSTS_MARK_END)
        post = after_end
    else:
        pre = current
        post = ""

    body_lines = [HOSTS_MARK_BEGIN, "# DO NOT EDIT - managed by FocusFortress"]
    seen: set[str] = set()
    for pat in domains:
        d = _extract_domain(pat)
        if not d:
            continue
        for v in _expand_variants(d):
            if v in seen:
                continue
            seen.add(v)
            body_lines.append(f"{REDIRECT_IP} {v}")
            body_lines.append(f"::1 {v}")
    body_lines.append(HOSTS_MARK_END)

    new_content = pre.rstrip() + "\n\n" + "\n".join(body_lines) + "\n" + post.lstrip("\n")

    was_ro = False
    try:
        st = os.stat(HOSTS_FILE)
        was_ro = not bool(st.st_mode & stat.S_IWRITE)
        if was_ro:
            os.chmod(HOSTS_FILE, stat.S_IWRITE)
    except Exception:
        pass

    # Write atomically: a crash mid-write must never leave a half-written
    # system hosts file. We write to a temp file in the SAME directory (so
    # os.replace is an atomic rename on the same volume) then swap it in.
    target_dir = os.path.dirname(str(HOSTS_FILE)) or "."
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".ff-hosts-", dir=target_dir)
        try:
            # Match the previous Path.write_text behaviour: default newline
            # translation (so "\n" becomes the platform newline on write).
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            os.replace(tmp_path, HOSTS_FILE)
            tmp_path = None  # successfully consumed by replace
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
    except PermissionError:
        # We are probably not elevated; surface the error upstream
        raise
    finally:
        if was_ro:
            try:
                os.chmod(HOSTS_FILE, stat.S_IREAD)
            except Exception:
                pass


def clear_block_section() -> None:
    write_block_section([])


def flush_dns() -> None:
    import subprocess
    try:
        subprocess.run(
            ["ipconfig", "/flushdns"],
            check=False, capture_output=True, creationflags=0x08000000,
        )
    except Exception:
        pass
