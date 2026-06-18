#!/usr/bin/env python3
"""Egress allowlist proxy (#119c) — let the jail reach CHOSEN dev hosts, nothing else.

The sandbox jail's egress is hard-blocked to loopback only (deploy/egress-setup.sh:
a cgroup-scoped iptables rule). The jail's `claude` reaches Anthropic via the
credential broker (#119b, also loopback); this proxy is the OTHER permitted loopback
exit — a tiny CONNECT forward-proxy so the agent's tools (git / pip / npm / curl) can
still reach an ALLOWLISTED set of dev hosts (github, pypi, npm, …) while every other
destination is refused. Together (broker + this proxy + the cgroup firewall) that is
option E of the #119 design: domain-based filtering with no bypass.

Why a CONNECT proxy and not an IP allowlist: Anthropic / GitHub / PyPI are CDN-fronted,
so their IPs rotate and a CDN range hosts thousands of other sites — an IP allowlist is
both fragile and leaky. A CONNECT proxy allowlists by the HOSTNAME in the CONNECT line
and merely TUNNELS the TLS (no MITM, no cert), so it is exact and needs no upkeep.

The jail is pointed here with HTTPS_PROXY (set by deploy/sandbox-claude.sh). Tools that
ignore the proxy env simply can't get out (the firewall drops them) — that is the
"proxy is the only exit" guarantee, not a leak.

P0: this proxy carries NO credential and never reads request bodies — it only reads the
CONNECT request line, checks the host against the allowlist, and splices bytes. It can
never touch the subscription token (which lives only in the broker).

Usage:  egress-proxy.py [--port N] [--allow a.com,b.com,...]
Env:    EGRESS_PROXY_PORT, EGRESS_ALLOW_HOSTS (comma/space separated)
Host matching: exact host OR a dot-suffix (an entry ``github.com`` matches
``github.com`` and ``api.github.com``, but not ``evilgithub.com``).
"""

import argparse
import os
import re
import select
import socket
import sys
import threading

# Default dev-host allowlist: git hosting, the Python and Node registries, and the
# Anthropic API (a fallback path when the credential broker is off — harmless when on,
# since `claude` then dials the broker on loopback, which NO_PROXY exempts).
_DEFAULT_ALLOW = (
    "api.anthropic.com",
    "github.com", "githubusercontent.com", "codeload.github.com",
    "pypi.org", "pythonhosted.org",
    "registry.npmjs.org", "npmjs.org",
)

_CONNECT_RE = re.compile(rb"^CONNECT\s+([^\s:]+):(\d+)\s+HTTP/1\.[01]", re.IGNORECASE)
_BUF = 65536


def _host_allowed(host: str, allow: frozenset) -> bool:
    """Exact host or a dot-suffix match (``github.com`` ⊇ ``api.github.com``)."""
    host = host.lower().strip(".")
    return any(host == a or host.endswith("." + a) for a in allow)


def _pump(a: socket.socket, b: socket.socket) -> None:
    """Splice bytes both ways until either side closes (no buffering of payload)."""
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
        # Read just the request line + headers (until CRLFCRLF) — never the body.
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = client.recv(_BUF)
            if not chunk:
                return
            head += chunk
            if len(head) > 16384:  # an absurd request line — drop
                return
        m = _CONNECT_RE.match(head)
        if not m:
            # Only CONNECT (HTTPS tunnels) is supported; plain-HTTP proxying is refused.
            client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        # The host in a CONNECT line is already ASCII (IDNs arrive as punycode), so a
        # plain ASCII decode is correct; an "idna" decode here raises and silently aborts.
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
    srv.bind(("127.0.0.1", port))   # loopback only — the jail reaches it via shared netns
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
    ap = argparse.ArgumentParser(description="Sandbox egress allowlist proxy (#119c).")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("EGRESS_PROXY_PORT", "8790")))
    ap.add_argument("--allow", default=os.environ.get("EGRESS_ALLOW_HOSTS", ""))
    args = ap.parse_args()
    extra = [h for h in re.split(r"[,\s]+", args.allow.strip().lower()) if h]
    allow = frozenset(_DEFAULT_ALLOW) | frozenset(extra)
    return serve(args.port, allow)


if __name__ == "__main__":
    raise SystemExit(main())
