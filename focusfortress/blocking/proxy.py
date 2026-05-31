"""Local HTTP/HTTPS blocking proxy.

Handles:
  - HTTP GET/POST/... -> inspects URL, blocks or forwards.
  - HTTPS via CONNECT -> inspects host[:port] against the rule set (path-level
    blocking over HTTPS is not possible without MITM, which we avoid).
  - Serves the custom block page.

System integration: we set the HKCU WinINET proxy to 127.0.0.1:<port>.
Firefox/Chrome (on Windows) honour this by default.

Design notes (matter a lot for correctness):
  * The handler advertises ``HTTP/1.0`` so ``BaseHTTPRequestHandler`` always
    closes the client connection after each request. That sidesteps every
    pipelining / keep-alive interaction with downstream browsers.
  * Upstream HTTP is forwarded via ``http.client.HTTPConnection`` so chunked
    transfer encoding, Content-Length, and other framing edge cases are
    handled by the standard library. We always send ``Connection: close``
    upstream so we get a clean EOF when the body is done.
  * Hop-by-hop headers (RFC 7230 6.1) are stripped both upstream and
    downstream; otherwise things like ``Transfer-Encoding`` and
    ``Connection: keep-alive`` end up forwarded through to peers that no
    longer understand the original framing.
  * The CONNECT tunnel does NO content inspection - this proxy never MITMs
    TLS. It blindly relays bytes, supports half-close, and uses TCP
    keepalive instead of an arbitrary idle timeout (which used to kill long
    uploads / streaming responses).
"""
from __future__ import annotations

import http.client
import logging
import select
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, List, Optional
from urllib.parse import urlparse

from .patterns import CompiledRules, compile_rules, host_is_blocked, url_is_blocked


log = logging.getLogger("focusfortress.proxy")


# Hop-by-hop headers per RFC 7230 6.1, plus the historical Proxy-Connection
# from HTTP/1.0. These MUST NOT be forwarded by an intermediary.
_HOP_BY_HOP = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
})


# Hostnames we will never proxy / block. Defense in depth: browsers should
# already bypass these via the WinINET ProxyOverride list, but if anything
# slips through we still keep local services working.
_LOCAL_HOSTS = frozenset({
    "localhost",
    "127.0.0.1",
    "::1",
    "[::1]",
    "0.0.0.0",
})


# Module-level observer callback: invoked with the hostname of every request
# that transits the proxy (allowed or blocked). Used by the stats tracker.
_observer: Optional[Callable[[str, bool], None]] = None


def set_site_observer(cb: Optional[Callable[[str, bool], None]]) -> None:
    """Register a callback ``(host, blocked)`` invoked on every proxied request."""
    global _observer
    _observer = cb


def _observe(host: str, blocked: bool) -> None:
    if _observer is None or not host:
        return
    try:
        _observer(host.lower(), blocked)
    except Exception:
        pass


def _is_local_host(host: str) -> bool:
    """True if ``host`` refers to the local machine and should never be blocked."""
    if not host:
        return False
    h = host.strip().lower()
    if h in _LOCAL_HOSTS:
        return True
    # IPv4 loopback range
    if h.startswith("127."):
        return True
    return False


class _Handler(BaseHTTPRequestHandler):
    # Injected at runtime by the server instance:
    rules: CompiledRules = compile_rules([], [])
    block_message: str = "This site is blocked by FocusFortress."
    block_page_html: str = ""
    proxy_port: int = 58123
    # Context about the active block (set by the engine each apply tick): the
    # name of the block doing the blocking and a short human detail such as
    # "1h 22m left". Empty strings mean "unknown / not provided".
    block_name: str = ""
    block_detail: str = ""

    # Force the framework to close the client connection after each response.
    # This sidesteps any chance of HTTP/1.1 keep-alive desync between us and
    # the browser. The browser will simply open a new connection per request,
    # which is cheap on loopback.
    protocol_version = "HTTP/1.0"

    # Don't let one slow client wedge the worker forever.
    timeout = 300

    # Silence default access logging.
    def log_message(self, *_a, **_kw) -> None:  # noqa: D401
        return

    # ---- helpers ----

    def _serve_block_page(self) -> None:
        # Build an optional "Blocked by 'Work' — 1h 22m left" banner from the
        # active-block context the engine pushes in. Falls back gracefully when
        # no context is set.
        import html as _html
        if self.block_name:
            ctx = f"Blocked by &lsquo;{_html.escape(self.block_name)}&rsquo;"
            if self.block_detail:
                ctx += f" &mdash; {_html.escape(self.block_detail)}"
        else:
            ctx = ""
        ctx_html = f"<p class='ctx'>{ctx}</p>" if ctx else ""
        html = self.block_page_html or f"""
        <!doctype html><html><head><meta charset='utf-8'>
        <title>Blocked</title>
        <style>body{{font-family:Segoe UI,Arial,sans-serif;background:#111;color:#eee;
        display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
        .card{{max-width:620px;padding:48px;text-align:center;background:#1b1b1b;border-radius:16px;
        box-shadow:0 10px 40px rgba(0,0,0,.4)}}
        h1{{margin:0 0 16px;font-weight:600}} p{{opacity:.8;line-height:1.5}}
        .ctx{{opacity:1;font-weight:600;color:#9ab;margin:0 0 18px}}</style>
        </head><body><div class='card'>
        <h1>Blocked by FocusFortress</h1>
        {ctx_html}
        <p>{self.block_message}</p>
        </div></body></html>
        """.strip()
        body = html.encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass

    def _read_request_body(self) -> bytes:
        """Read the entire request body, supporting both framing modes.

        - Content-Length: read exactly that many bytes.
        - Transfer-Encoding: chunked: decode the chunked stream into a single
          flat buffer (we re-frame it upstream as a normal Content-Length
          body, since http.client takes care of that).
        - Anything else: no body.
        """
        te = self.headers.get("Transfer-Encoding", "").lower()
        if "chunked" in te:
            buf = bytearray()
            while True:
                line = self.rfile.readline(8192)
                if not line:
                    break
                size_str = line.strip().split(b";", 1)[0]
                try:
                    size = int(size_str, 16)
                except ValueError:
                    break
                if size == 0:
                    # Drain optional trailers up to the terminating CRLF.
                    while True:
                        trailer = self.rfile.readline(8192)
                        if not trailer or trailer in (b"\r\n", b"\n"):
                            break
                    break
                remaining = size
                while remaining > 0:
                    part = self.rfile.read(remaining)
                    if not part:
                        return bytes(buf)
                    buf.extend(part)
                    remaining -= len(part)
                # CRLF after each chunk
                self.rfile.readline(8192)
            return bytes(buf)

        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return b""
        buf = bytearray()
        remaining = length
        while remaining > 0:
            part = self.rfile.read(min(65536, remaining))
            if not part:
                break
            buf.extend(part)
            remaining -= len(part)
        return bytes(buf)

    def _outbound_headers(self) -> dict:
        """Copy client request headers minus hop-by-hop, force Connection: close."""
        out: dict = {}
        for k, v in self.headers.items():
            if k.lower() in _HOP_BY_HOP:
                continue
            # http.client computes its own Content-Length / Host.
            if k.lower() in ("content-length", "host"):
                continue
            out[k] = v
        out["Connection"] = "close"
        return out

    # ---- HTTP ----

    def _do_http_method(self) -> None:
        target = self.path

        # Direct hit on the proxy itself (e.g. user typing the proxy URL into
        # a browser, or a browser auto-discovery probe). Nothing to forward.
        if not target.startswith(("http://", "https://")):
            self._serve_block_page()
            return

        # An absolute https:// URL arriving on a normal method (not CONNECT)
        # must NOT be forwarded: _forward_http speaks cleartext HTTP, so it
        # would send the request in the clear to port 443. HTTPS is only ever
        # handled via the CONNECT tunnel path. Refuse rather than downgrade.
        if target.startswith("https://"):
            try:
                self.send_error(400, "https requires CONNECT")
            except Exception:
                pass
            return

        # Decide blocking BEFORE consuming the body so we can drop large
        # requests cheaply.
        parsed = urlparse(target)
        host = parsed.hostname or ""
        port = parsed.port or 80

        # Loop / local-host guard. Never proxy back to ourselves and never
        # apply rules to local services - those should keep working in all
        # cases (defense in depth on top of the WinINET bypass list).
        if _is_local_host(host):
            if port == self.proxy_port:
                # Configuration tried to make us call ourselves.
                self.send_error(421, "Loopback refused")
                return
            self._forward_http(host, port, parsed, blocked=False)
            return

        if url_is_blocked(target, self.rules):
            _observe(host, True)
            try:
                self._read_request_body()
            except Exception:
                pass
            self._serve_block_page()
            return

        _observe(host, False)
        if not host:
            self.send_error(400, "Bad URL")
            return
        self._forward_http(host, port, parsed, blocked=False)

    def _forward_http(self, host: str, port: int, parsed, *, blocked: bool) -> None:
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        try:
            body = self._read_request_body()
        except Exception as e:
            log.debug("read body failed: %s", e)
            try:
                self.send_error(400, "Bad request body")
            except Exception:
                pass
            return

        headers = self._outbound_headers()

        try:
            conn = http.client.HTTPConnection(host, port, timeout=60)
            conn.request(self.command, path, body=body if body else None, headers=headers)
            resp = conn.getresponse()
        except Exception as e:
            log.debug("upstream http://%s:%d failed: %s", host, port, e)
            try:
                self.send_error(502, "Upstream connection failed")
            except Exception:
                pass
            return

        try:
            # Re-emit the status line and headers ourselves rather than
            # relaying raw bytes - this lets us strip hop-by-hop headers
            # and rewrite framing cleanly.
            self.send_response_only(resp.status, resp.reason or "")
            for k, v in resp.getheaders():
                if k.lower() in _HOP_BY_HOP:
                    continue
                # We're closing the connection after this response, so we
                # MUST NOT advertise chunked transfer to the client unless
                # we re-frame it - simplest: rewrite framing ourselves
                # using the entity body length we read.
                if k.lower() == "content-length":
                    # Will be re-issued below if appropriate.
                    continue
                self.send_header(k, v)
            self.send_header("Connection", "close")

            # Stream the body. For a single-shot response over a closing
            # connection, the simplest correct framing is to send the body
            # without Content-Length and rely on EOF. But many clients are
            # happier with an explicit length when we have one.
            cl = resp.getheader("Content-Length")
            if cl is not None:
                self.send_header("Content-Length", cl)
                self.end_headers()
                _stream_body(resp, self.wfile)
            else:
                # Unknown / chunked upstream length: read fully then send
                # with a known Content-Length so downstream is happy.
                # (We already stripped Transfer-Encoding from the headers.)
                payload = bytearray()
                while True:
                    try:
                        chunk = resp.read(65536)
                    except Exception:
                        break
                    if not chunk:
                        break
                    payload.extend(chunk)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(bytes(payload))
                except Exception:
                    pass
        finally:
            try:
                resp.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def do_GET(self) -> None: self._do_http_method()
    def do_POST(self) -> None: self._do_http_method()
    def do_PUT(self) -> None: self._do_http_method()
    def do_DELETE(self) -> None: self._do_http_method()
    def do_HEAD(self) -> None: self._do_http_method()
    def do_OPTIONS(self) -> None: self._do_http_method()
    def do_PATCH(self) -> None: self._do_http_method()

    # ---- HTTPS tunnelling ----

    def do_CONNECT(self) -> None:
        # self.path is e.g. "www.example.com:443"
        host, _, port_s = self.path.partition(":")
        try:
            port = int(port_s or "443")
        except ValueError:
            self.send_error(400)
            return

        # Loop guard - never tunnel to our own listener.
        if _is_local_host(host) and port == self.proxy_port:
            self.send_error(421, "Loopback refused")
            return

        # Local services: tunnel without consulting rules. Browsers should
        # already bypass these via ProxyOverride; this is defense in depth.
        if not _is_local_host(host) and host_is_blocked(host, self.rules):
            _observe(host, True)
            self.send_error(403, "Blocked by FocusFortress")
            return
        _observe(host, False)

        try:
            upstream = socket.create_connection((host, port), timeout=15)
        except Exception:
            try:
                self.send_error(502)
            except Exception:
                pass
            return

        # Once tunnelled, neither side should impose a short timeout - the
        # connection may legitimately sit idle for minutes (HTTP/2 streams,
        # large uploads where the server is busy processing, websockets).
        # We rely on TCP keepalive + peer close to detect dead connections.
        upstream.settimeout(None)
        _enable_keepalive(upstream)

        try:
            self.send_response(200, "Connection Established")
            self.end_headers()
            try:
                self.wfile.flush()
            except Exception:
                pass
        except Exception:
            try: upstream.close()
            except Exception: pass
            return

        client = self.connection
        try:
            client.settimeout(None)
        except Exception:
            pass
        _enable_keepalive(client)

        try:
            _pump_tunnel(client, upstream)
        finally:
            try: upstream.shutdown(socket.SHUT_RDWR)
            except Exception: pass
            try: upstream.close()
            except Exception: pass


def _enable_keepalive(sock: socket.socket) -> None:
    """Enable TCP keepalive on a socket so dead peers are noticed."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except Exception:
        pass


def _stream_body(resp: http.client.HTTPResponse, wfile) -> None:
    while True:
        try:
            chunk = resp.read(65536)
        except Exception:
            break
        if not chunk:
            break
        try:
            wfile.write(chunk)
        except Exception:
            break


def _pump_tunnel(a: socket.socket, b: socket.socket) -> None:
    """Bidirectional byte pump with proper half-close semantics.

    The previous implementation tore down both directions as soon as either
    side returned EOF or after 30 seconds of silence. That broke long
    uploads and any protocol that uses TCP half-close (e.g. some websocket
    teardowns). We now:

      * Track each direction independently and only stop reading from a
        side once IT has signalled EOF.
      * Forward EOF as a SHUT_WR on the peer so it sees a clean close.
      * Use no idle timeout - rely on TCP keepalive / RST.
    """
    a_open = True  # can we still read from a?
    b_open = True  # can we still read from b?
    while a_open or b_open:
        read_set = []
        if a_open: read_set.append(a)
        if b_open: read_set.append(b)
        if not read_set:
            break
        try:
            r, _, x = select.select(read_set, [], read_set, None)
        except (OSError, ValueError):
            break
        if x:
            break
        for s in r:
            try:
                data = s.recv(65536)
            except (BlockingIOError, InterruptedError):
                continue
            except (ConnectionResetError, ConnectionAbortedError):
                if s is a: a_open = False
                else: b_open = False
                continue
            except OSError:
                if s is a: a_open = False
                else: b_open = False
                continue
            if not data:
                # Half-close: stop reading from this side, tell the peer
                # we're done writing in this direction.
                peer = b if s is a else a
                try:
                    peer.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                if s is a: a_open = False
                else: b_open = False
                continue
            peer = b if s is a else a
            try:
                peer.sendall(data)
            except OSError:
                # Write side broken - stop reading the source.
                if s is a: a_open = False
                else: b_open = False


class BlockingProxy:
    def __init__(self, port: int = 58123) -> None:
        self.port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._rules = compile_rules([], [])
        self._msg = "This site is blocked by FocusFortress."
        self._html = ""

    def set_rules(self, sites: List[str], exceptions: List[str]) -> None:
        self._rules = compile_rules(sites, exceptions)
        _Handler.rules = self._rules

    def set_block_page(self, message: str, html: str = "") -> None:
        self._msg = message or self._msg
        self._html = html or ""
        _Handler.block_message = self._msg
        _Handler.block_page_html = self._html

    def set_block_context(self, block_name: str = "", detail: str = "") -> None:
        """Set the active-block context shown on the default block page.

        ``block_name`` is the name of the block doing the blocking and
        ``detail`` a short human string (e.g. "1h 22m left"). Pass empty
        strings to clear the banner.
        """
        _Handler.block_name = block_name or ""
        _Handler.block_detail = detail or ""

    def start(self) -> None:
        if self._server:
            return
        _Handler.rules = self._rules
        _Handler.block_message = self._msg
        _Handler.block_page_html = self._html
        _Handler.proxy_port = self.port
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="ff-proxy", daemon=True
        )
        self._thread.start()
        log.info("proxy listening on 127.0.0.1:%d", self.port)

    def stop(self) -> None:
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
        self._server = None
        self._thread = None
