#!/usr/bin/env python3
"""Credential broker: keeps the OAuth token out of the jail.

- host process on loopback; jailed `claude` gets a dummy credential
- rewrites `Authorization` to the real bearer, streams SSE back
- never injects `ANTHROPIC_API_KEY`; strips inbound `x-api-key`
- token material is never logged
- options: `--port`, `--creds`, `--host`, `CRED_BROKER_*` env vars
"""

import argparse
import http.client
import http.server
import json
import os
import socketserver
import sys
import threading

# Hop-by-hop headers (RFC 7230) are never forwarded.
# - plus headers we manage: Host, Authorization, framing
_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade"}
_DROP_REQ = _HOP | {"host", "authorization", "content-length", "x-api-key"}
_DROP_RESP = _HOP | {"content-length"}

# Inbound method and path allowlist.
# - the broker attaches the real bearer to anything relayed
# - CLI only POSTs `/v1/messages` and `/v1/messages/count_tokens`
# - anything else gets 403
_ALLOW: tuple[tuple[str, str], ...] = (("POST", "/v1/messages"),)


# Per-socket idle-read timeout on the upstream connection.
# - caps one blocking read, not a total deadline
# - live SSE streams emit events every few seconds
# - bounds a wedged upstream to 3 minutes
_UPSTREAM_IDLE_TIMEOUT = 180


def _path_allowed(method: str, path: str) -> bool:
    """True if method and path match the inbound allowlist.

    - path matched by prefix; query string ignored
    """
    base = path.split("?", 1)[0]
    # Exact match or true path-segment prefix only.
    # - a bare prefix match let `/v1/messages_evil` through
    return any(method == m and (base == p or base.startswith(p + "/")) for m, p in _ALLOW)


class _Creds:
    """Reads the real OAuth token, reloading when the file changes.

    - picks up the refresher's rotation; never logs the value
    """

    def __init__(self, path: str):
        self._path = os.path.expanduser(path)
        self._mtime = 0.0
        self._token = None
        self._lock = threading.Lock()

    def token(self):
        with self._lock:
            try:
                m = os.stat(self._path).st_mtime
                if m != self._mtime or self._token is None:
                    with open(self._path, encoding="utf-8") as fh:
                        self._token = json.load(fh)["claudeAiOauth"]["accessToken"]
                    self._mtime = m
            except (OSError, ValueError, KeyError, TypeError):
                return None
            return self._token


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # Injected by the server factory.
    creds: "_Creds" = None
    upstream_host: str = "api.anthropic.com"

    def log_message(self, *a):  # quiet; we log our own lines
        pass

    def _read_request_body(self) -> bytes:
        """Read the request body, Content-Length or chunked.

        - chunked bodies would otherwise be relayed empty
        - returns the fully buffered body for re-framing upstream
        """
        te = (self.headers.get("transfer-encoding") or "").lower()
        if "chunked" in te:
            body = bytearray()
            while True:
                size_line = self.rfile.readline(65536).split(b";", 1)[0].strip()
                if not size_line:
                    continue
                try:
                    size = int(size_line, 16)
                except ValueError:
                    break                          # malformed framing: stop and send
                if size == 0:
                    while self.rfile.readline(65536) not in (b"\r\n", b"\n", b""):
                        pass                       # consume trailers up to blank line
                    break
                body += self.rfile.read(size)
                self.rfile.read(2)                 # CRLF after each chunk
            return bytes(body)
        n = int(self.headers.get("content-length") or 0)
        return self.rfile.read(n) if n else b""

    def _proxy(self):
        # Reject disallowed callers before touching token or upstream.
        if not _path_allowed(self.command, self.path):
            self.send_error(403, "broker: method/path not allowed")
            sys.stderr.write(f"[broker] BLOCKED {self.command} {self.path.split('?')[0]} -> 403\n")
            return
        token = self.creds.token()
        if not token:
            self.send_error(503, "broker: no subscription credential")
            # Log an unreadable creds file instead of returning silently.
            # - otherwise turns fail with a generic error, no journal trace
            sys.stderr.write("[broker] NO CREDENTIAL (host login dead?) "
                             f"{self.command} {self.path.split('?')[0]} -> 503\n")
            return
        body = self._read_request_body()

        out_headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in _DROP_REQ}
        out_headers["Host"] = self.upstream_host
        out_headers["Authorization"] = f"Bearer {token}"   # real token injected here

        conn = http.client.HTTPSConnection(self.upstream_host, timeout=_UPSTREAM_IDLE_TIMEOUT)
        try:
            conn.request(self.command, self.path, body=body or None, headers=out_headers)
            resp = conn.getresponse()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in _DROP_RESP:
                    self.send_header(k, v)            # keep content-encoding/-type, `anthropic-*`
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                # Use `read1()` so SSE frames flush as they arrive.
                # - `read(65536)` blocks until 64 KB or close
                # - that buffered short replies and killed token streaming
                chunk = resp.read1(65536)            # stream SSE frames as they arrive
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            sys.stderr.write(f"[broker] {self.command} {self.path.split('?')[0]} -> {resp.status}\n")
        except Exception as exc:                       # upstream or network failure
            try:
                self.send_error(502, f"broker upstream error: {type(exc).__name__}")
            except Exception:
                pass
        finally:
            conn.close()

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _proxy


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    # Log an expected client disconnect as one line.
    # - reaped turns reset the connection; default traceback is noise
    # - disconnects during the proxied body are handled in `_proxy`
    # - this covers request-body and keep-alive reads
    # - full traceback kept for anything else
    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            sys.stderr.write(f"[broker] client {client_address} disconnected "
                             f"({type(exc).__name__})\n")
            return
        super().handle_error(request, client_address)


def build_server(port: int, creds_path: str, upstream: str) -> _Server:
    handler = type("BoundHandler", (_Handler,),
                   {"creds": _Creds(creds_path), "upstream_host": upstream})
    return _Server(("127.0.0.1", port), handler)


def main() -> int:
    ap = argparse.ArgumentParser(description="Subscription credential broker.")
    ap.add_argument("--port", type=int, default=int(os.environ.get("CRED_BROKER_PORT", "8789")))
    ap.add_argument("--creds", default=os.environ.get("CRED_BROKER_CREDS", "~/.claude/.credentials.json"))
    ap.add_argument("--host", default=os.environ.get("CRED_BROKER_UPSTREAM", "api.anthropic.com"))
    args = ap.parse_args()
    # Refuse to start when an API key is set.
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        sys.stderr.write("[broker] REFUSING TO START: ANTHROPIC_API_KEY/AUTH_TOKEN in env "
                         "(subscription-only; unset it)\n")
        return 2
    srv = build_server(args.port, args.creds, args.host)
    sys.stderr.write(f"[broker] listening on 127.0.0.1:{args.port} -> https://{args.host} "
                     f"(creds: {args.creds})\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
