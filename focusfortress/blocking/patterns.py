"""Pattern matching for website rules."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Tuple


@dataclass
class CompiledRules:
    block_all: bool
    regexes: List[re.Pattern]
    exception_regexes: List[re.Pattern]


def _pattern_to_regex(pattern: str) -> re.Pattern:
    """Convert a FocusFortress pattern to a regex matched against a full URL.

    Rules:
      - `*` matches any text (including /).
      - A bare domain like `facebook.com` matches the domain + any subdomain + any path.
      - `reddit.com/r/funny` matches that exact URL prefix.
      - `google.com/*q=*unicorn*` uses `*` as a wildcard inside the URL.
      - `youtube.com/channelname` works the same way (prefix match after escaping).

    The generated regex tolerates an optional ``:port`` after the host so
    that a rule like ``example.com`` still matches
    ``http://example.com:8080/foo`` (browsers include the port for
    non-default ports).
    """
    p = pattern.strip().lower()
    if not p:
        # Never matches
        return re.compile(r"(?!x)x")

    # Strip scheme from user input
    p = re.sub(r"^[a-z]+://", "", p)

    # Special case: entire internet
    if p == "*.*":
        return re.compile(r".*")

    # Split path and host for smart domain handling
    host, sep, path = p.partition("/")

    # Strip a user-supplied port so we never accidentally embed `:80` inside
    # the escaped host literal - we always allow an optional port below.
    host = re.sub(r":\d+$", "", host)

    if "*" in host:
        # Wildcards in host - build direct regex
        host_re = re.escape(host).replace(r"\*", ".*")
    else:
        # Bare-domain semantics: match domain and all subdomains
        host_re = r"(?:[a-z0-9.-]+\.)?" + re.escape(host)

    # Optional ``:port``. Any digits, since user rules don't pin a port.
    port_re = r"(?::\d+)?"

    if sep:
        path_re = re.escape(path).replace(r"\*", ".*")
        full = rf"^https?://{host_re}{port_re}/{path_re}"
    else:
        full = rf"^https?://{host_re}{port_re}(?:/.*)?$"

    return re.compile(full, re.IGNORECASE)


def compile_rules(sites: Iterable[str], exceptions: Iterable[str]) -> CompiledRules:
    block_all = False
    regs: List[re.Pattern] = []
    for s in sites:
        if s.strip() == "*.*":
            block_all = True
        regs.append(_pattern_to_regex(s))
    excs = [_pattern_to_regex(s) for s in exceptions]
    return CompiledRules(block_all=block_all, regexes=regs, exception_regexes=excs)


def url_is_blocked(url: str, rules: CompiledRules) -> bool:
    for ex in rules.exception_regexes:
        if ex.search(url):
            return False
    for r in rules.regexes:
        if r.search(url):
            return True
    return False


_LOCAL_HOSTS = frozenset({
    "localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0",
})


def host_is_blocked(host: str, rules: CompiledRules) -> bool:
    """Whether a bare hostname (no scheme/path) should be blocked.

    Loopback/local hostnames are never blocked here so local services keep
    working even if a user rule would otherwise match them. This is defense
    in depth on top of the proxy's WinINET bypass list.
    """
    if not host:
        return False
    h = host.strip().lower()
    if h in _LOCAL_HOSTS or h.startswith("127."):
        return False
    return url_is_blocked(f"http://{h}/", rules)
