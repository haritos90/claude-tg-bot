#!/bin/bash
# deploy/egress-teardown.sh — fully revert deploy/egress-setup.sh (#119c).
# Removes the cgroup-scoped jump from OUTPUT and deletes the SBX_EGRESS chain, for
# both IPv4 and IPv6. Leaves the /sys/fs/cgroup/sbx cgroup in place (harmless and may
# still hold a live jail). Idempotent; safe to run when nothing was set up.
set -uo pipefail

CG_ROOT="${SBX_CGROUP:-/sys/fs/cgroup/sbx}"
CG_NAME="$(basename "$CG_ROOT")"
CHAIN="SBX_EGRESS"

for ipt in iptables ip6tables; do
  command -v "$ipt" >/dev/null 2>&1 || continue
  # Remove every copy of the jump (a re-run could in theory have added more than one).
  while "$ipt" -C OUTPUT -m cgroup --path "$CG_NAME" -j "$CHAIN" 2>/dev/null; do
    "$ipt" -D OUTPUT -m cgroup --path "$CG_NAME" -j "$CHAIN" 2>/dev/null || break
  done
  "$ipt" -F "$CHAIN" 2>/dev/null || true
  "$ipt" -X "$CHAIN" 2>/dev/null || true
done

echo "[egress-teardown] removed $CHAIN jump + chain (cgroup $CG_ROOT left in place)"
