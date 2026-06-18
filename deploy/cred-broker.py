#!/usr/bin/env python3
"""Credential broker (#119b) — keep the subscription OAuth token OUT of the jail.

The core insight of #119: no egress control can protect a token that lives INSIDE the
jail (the agent can read it and print/POST it). So the token must not be in the jail.

This standalone host process runs OUTSIDE the bubblewrap jail and listens on
loopback. The jailed `claude` is pointed at it with ``ANTHROPIC_BASE_URL`` and is given
only a DUMMY credential. The broker rewrites the ``Authorization`` header to the REAL
subscription OAuth bearer (read from the host's ``~/.claude/.credentials.json``, kept
fresh by the #191 refresher) and forwards to ``api.anthropic.com``, streaming the SSE
reply back. So the real token is USABLE (via the broker) but UN-extractable from the
jail: there is nothing real inside to read, print, or POST.

Recon (#119a) confirmed `claude` honours ``ANTHROPIC_BASE_URL`` under subscription
auth and sends ``Authorization: Bearer <oauth>`` + ``anthropic-beta: oauth-2025-04-20``
to ``POST /v1/messages?beta=true`` — so this plain-HTTP-to-broker variant needs NO
MITM/TLS-termination.

P0 (subscription billing): the broker forwards an OAuth ``Authorization: Bearer`` only.
It NEVER injects ``ANTHROPIC_API_KEY`` / ``ANTHROPIC_AUTH_TOKEN`` (those flip to paid
per-token billing). It also strips any inbound ``x-api-key`` so a jailed client can't
sneak API-key billing in.

Usage:  cred-broker.py [--port N] [--creds PATH] [--host api.anthropic.com]
Env:    CRED_BROKER_PORT, CRED_BROKER_CREDS, CRED_BROKER_UPSTREAM
Token material is NEVER logged.
"""

import argparse
import http.client
import http.server
import json
import os
import socketserver
import sys
import threading

# Hop-by-hop headers (RFC 7230 §6.1) — never forwarded. Plus the ones we manage
# ourselves: Host (set to the upstream), Authorization (replaced), and the
# request/response framing headers (we re-read the body / re-chunk the response).
_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade"}
_DROP_REQ = _HOP | {"host", "authorization", "content-length", "x-api-key"}
_DROP_RESP = _HOP | {"content-length"}


class _Creds:
    """Reads the real OAuth access token from the host creds file, re-reading when the
    file changes (so the #191 refresher's rotation is picked up). Never logs the value."""

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

    def log_message(self, *a):  # quiet; we log our own one-liners (no token)
        pass

    def _proxy(self):
        token = self.creds.token()
        if not token:
            self.send_error(503, "broker: no subscription credential")
            return
        body = b""
        n = int(self.headers.get("content-length") or 0)
        if n:
            body = self.rfile.read(n)

        out_headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in _DROP_REQ}
        out_headers["Host"] = self.upstream_host
        out_headers["Authorization"] = f"Bearer {token}"   # the REAL token, injected here

        conn = http.client.HTTPSConnection(self.upstream_host, timeout=600)
        try:
            conn.request(self.command, self.path, body=body or None, headers=out_headers)
            resp = conn.getresponse()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in _DROP_RESP:
                    self.send_header(k, v)            # keep content-encoding/-type, anthropic-*
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                chunk = resp.read(65536)              # streams SSE as it arrives
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            sys.stderr.write(f"[broker] {self.command} {self.path.split('?')[0]} -> {resp.status}\n")
        except Exception as exc:                       # upstream/network failure
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


def build_server(port: int, creds_path: str, upstream: str) -> _Server:
    handler = type("BoundHandler", (_Handler,),
                   {"creds": _Creds(creds_path), "upstream_host": upstream})
    return _Server(("127.0.0.1", port), handler)


def main() -> int:
    ap = argparse.ArgumentParser(description="Subscription credential broker (#119b).")
    ap.add_argument("--port", type=int, default=int(os.environ.get("CRED_BROKER_PORT", "8789")))
    ap.add_argument("--creds", default=os.environ.get("CRED_BROKER_CREDS", "~/.claude/.credentials.json"))
    ap.add_argument("--host", default=os.environ.get("CRED_BROKER_UPSTREAM", "api.anthropic.com"))
    args = ap.parse_args()
    # P0 guard: refuse to start if an API key is in the env (it must never reach here).
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
