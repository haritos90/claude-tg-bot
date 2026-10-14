#!/bin/bash
# Fully reverts the egress setup script.
# - Removes cgroup jump and chain, IPv4 and IPv6
# - Keeps the sbx cgroup; it may hold live jails
# - Idempotent; safe when nothing was set up
set -uo pipefail

CG_ROOT="${SBX_CGROUP:-/sys/fs/cgroup/sbx}"
CG_NAME="$(basename "$CG_ROOT")"
CHAIN="SBX_EGRESS"

for ipt in iptables ip6tables; do
  command -v "$ipt" >/dev/null 2>&1 || continue
  # Remove every copy of the jump.
  while "$ipt" -C OUTPUT -m cgroup --path "$CG_NAME" -j "$CHAIN" 2>/dev/null; do
    "$ipt" -D OUTPUT -m cgroup --path "$CG_NAME" -j "$CHAIN" 2>/dev/null || break
  done
  "$ipt" -F "$CHAIN" 2>/dev/null || true
  "$ipt" -X "$CHAIN" 2>/dev/null || true
done

echo "[egress-teardown] removed $CHAIN jump + chain (cgroup $CG_ROOT left in place)"
