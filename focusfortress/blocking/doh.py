"""Block public DNS-over-HTTPS endpoints to stop browsers bypassing the hosts file.

Each entry here is a well-known DoH hostname. When enabled, these are injected
into the hosts file alongside a block. Entries the user explicitly adds to the
``doh_allowlist`` setting are skipped - so users who run their own DoH service
(e.g. NextDNS) can keep it working.
"""
from __future__ import annotations

from typing import Iterable, List


# Public DoH resolvers that browsers commonly use by default.
DEFAULT_DOH_DOMAINS: tuple[str, ...] = (
    "mozilla.cloudflare-dns.com",
    "cloudflare-dns.com",
    "one.one.one.one",
    "dns.google",
    "dns.google.com",
    "doh.opendns.com",
    "dns.quad9.net",
    "dns9.quad9.net",
    "dns10.quad9.net",
    "dns.adguard.com",
    "dns.adguard-dns.com",
    "doh.cleanbrowsing.org",
    "doh.pub",
    "doh.360.cn",
    "dns.controld.com",
    "freedns.controld.com",
    # Chromium's auto-upgrade probe list
    "chrome.cloudflare-dns.com",
)


def resolve_blocklist(allowlist: Iterable[str]) -> List[str]:
    """Return the DoH domains to block after removing anything on the allowlist.

    Matching is substring-based on the bare domain (case-insensitive) so a user
    can, for example, allow ``nextdns.io`` and we will leave every nextdns
    subdomain alone even though they're not in our default list anyway.
    """
    allow = {a.strip().lower() for a in allowlist if a.strip()}
    out: list[str] = []
    for d in DEFAULT_DOH_DOMAINS:
        dl = d.lower()
        if any(a in dl or dl.endswith("." + a) or dl == a for a in allow):
            continue
        out.append(d)
    return out
