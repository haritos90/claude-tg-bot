#!/usr/bin/env python3
"""Egress allowlist proxy: jail reaches chosen dev hosts only.

- a cgroup iptables rule blocks jail egress except loopback
- CONNECT proxy allowlists by hostname and tunnels TLS
- hostname filtering beats IP allowlists for CDN-fronted hosts
- carries no credential and never reads request bodies
- hosts match exactly or by dot-suffix, not `evilgithub.com`
"""

import argparse
import os
import re
import select
import socket
import sys
import threading

# Default dev-host allowlist: git hosting, registries, Anthropic API.
# - Anthropic is a fallback when the broker is off
# - harmless otherwise: loopback broker is exempt via `NO_PROXY`
_DEFAULT_ALLOW = (
    "api.anthropic.com",
    "github.com", "githubusercontent.com", "codeload.github.com",
    "pypi.org", "pythonhosted.org",
    "registry.npmjs.org", "npmjs.org",
)

_CONNECT_RE = re.compile(rb"^CONNECT\s+([^\s:]+):(\d+)\s+HTTP/1\.[01]", re.IGNORECASE)
_BUF = 65536


def _host_allowed(host: str, allow: frozenset) -> bool:
    """Exact host or dot-suffix match."""
    host = host.lower().strip(".")
    return any(host == a or host.endswith("." + a) for a in allow)


def _pump(a: socket.socket, b: socket.socket) -> None:
    """Splice bytes both ways until either side closes."""
    socks = [a, b]
    try:
        while True:
            r, _, x = select.select(socks, [], socks, 300)
            if x or not r:
                break
            for s in r:
                data = s.recv(_BUF)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        pass


def _handle(client: socket.socket, allow: frozenset) -> None:
    client.settimeout(30)
    try:
        # Read only request line and headers, never the body.
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = client.recv(_BUF)
            if not chunk:
                return
            head += chunk
            if len(head) > 16384:  # absurd request line: drop
                return
        m = _CONNECT_RE.match(head)
        if not m:
            # Only CONNECT is supported; plain-HTTP proxying is refused.
            client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        # CONNECT hosts are already ASCII (IDNs arrive as punycode).
        # - an idna decode would raise and silently abort
        host = m.group(1).decode("ascii", "ignore")
        port = int(m.group(2))
        if not _host_allowed(host, allow) or port not in (443, 22):
            sys.stderr.write(f"[egress] DENY {host}:{port}\n")
            client.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n"
                           b"egress-proxy: host not in allowlist\r\n")
            return
        try:
            upstream = socket.create_connection((host, port), timeout=30)
        except OSError as exc:
            sys.stderr.write(f"[egress] FAIL {host}:{port} ({type(exc).__name__})\n")
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        sys.stderr.write(f"[egress] ALLOW {host}:{port}\n")
        client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        upstream.settimeout(None)
        client.settimeout(None)
        try:
            _pump(client, upstream)
        finally:
            upstream.close()
    except (OSError, ValueError):
        pass
    finally:
        client.close()


def serve(port: int, allow: frozenset) -> int:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))   # loopback only; jail shares netns
    srv.listen(128)
    sys.stderr.write(f"[egress] listening on 127.0.0.1:{port}; allow={sorted(allow)}\n")
    try:
        while True:
            client, _ = srv.accept()
            threading.Thread(target=_handle, args=(client, allow), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Sandbox egress allowlist proxy.")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("EGRESS_PROXY_PORT", "8790")))
    ap.add_argument("--allow", default=os.environ.get("EGRESS_ALLOW_HOSTS", ""))
    args = ap.parse_args()
    extra = [h for h in re.split(r"[,\s]+", args.allow.strip().lower()) if h]
    allow = frozenset(_DEFAULT_ALLOW) | frozenset(extra)
    return serve(args.port, allow)


if __name__ == "__main__":
    raise SystemExit(main())
