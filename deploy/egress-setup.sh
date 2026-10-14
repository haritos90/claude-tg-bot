#!/bin/bash
# Confines sandbox egress to loopback via a cgroup-scoped chain.
# - Only broker and proxy ports are reachable
# - Never touches OUTPUT policy; one jump, sandbox cgroup only
# - Matches by cgroup, since jail uid maps to outer root
# - Reverted by egress-teardown.sh; fully undoable
# - Idempotent; args: broker port, proxy port (8789/8790)
set -euo pipefail

CG_ROOT="${SBX_CGROUP:-/sys/fs/cgroup/sbx}"
CG_NAME="$(basename "$CG_ROOT")"        # iptables --path is relative to the cgroup2 root
CHAIN="SBX_EGRESS"
BROKER_PORT="${1:-8789}"
PROXY_PORT="${2:-8790}"

# Load xt_cgroup; iptables does not always autoload it.
modprobe xt_cgroup 2>/dev/null || true
# Load conntrack explicitly; its module is not always autoloaded.
# - Missing module aborts setup, leaving egress unenforced
# - Best-effort; final verification is the real backstop
modprobe nf_conntrack 2>/dev/null || true

# Sandbox cgroup: firewall match and per-jail resource container.
# - Enable memory, pids, cpu controllers so leaves set limits
# - Controller-enable failure is non-fatal; egress needs only membership
mkdir -p "$CG_ROOT"
PARENT_CTRL="$(dirname "$CG_ROOT")/cgroup.controllers"
for c in memory pids cpu; do
  if grep -qw "$c" "$PARENT_CTRL" 2>/dev/null; then
    echo "+$c" > "$CG_ROOT/cgroup.subtree_control" 2>/dev/null || true
  fi
done
# Sweep stale empty leaves from previous runs.
# - Leaves have no post-exit cleanup hook
for d in "$CG_ROOT"/*/; do
  [ -d "$d" ] || continue
  if [ ! -s "$d/cgroup.procs" ]; then rmdir "$d" 2>/dev/null || true; fi
done

# Egress chain plus cgroup-scoped jump, IPv4 and IPv6.
# - IPv4: allow loopback broker and proxy ports; reject rest
# - IPv6: reject all egress, closing a bypass
add_v4() {
  iptables -N "$CHAIN" 2>/dev/null || iptables -F "$CHAIN"
  iptables -A "$CHAIN" -o lo -p tcp --dport "$BROKER_PORT" -j ACCEPT
  iptables -A "$CHAIN" -o lo -p tcp --dport "$PROXY_PORT"  -j ACCEPT
  iptables -A "$CHAIN" -o lo -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  iptables -A "$CHAIN" -j REJECT --reject-with icmp-port-unreachable
  iptables -C OUTPUT -m cgroup --path "$CG_NAME" -j "$CHAIN" 2>/dev/null \
    || iptables -I OUTPUT 1 -m cgroup --path "$CG_NAME" -j "$CHAIN"
}
add_v6() {
  ip6tables -N "$CHAIN" 2>/dev/null || ip6tables -F "$CHAIN"
  ip6tables -A "$CHAIN" -o lo -j ACCEPT
  ip6tables -A "$CHAIN" -j REJECT --reject-with icmp6-port-unreachable
  ip6tables -C OUTPUT -m cgroup --path "$CG_NAME" -j "$CHAIN" 2>/dev/null \
    || ip6tables -I OUTPUT 1 -m cgroup --path "$CG_NAME" -j "$CHAIN"
}
add_v4
add_v6 2>/dev/null || true   # a box without ip6tables still gets the v4 confinement

# Verify the IPv4 cgroup jump actually landed.
# - Partial or missing jump must never pass silently
# - Caller logs loudly when egress is not enforced
# - IPv6 is best-effort; hosts may lack ip6tables
if ! iptables -C OUTPUT -m cgroup --path "$CG_NAME" -j "$CHAIN" 2>/dev/null; then
  echo "[egress-setup] ERROR: cgroup egress jump did NOT apply (chain=$CHAIN, cgroup=$CG_NAME)" >&2
  exit 1
fi

echo "[egress-setup] cgroup=$CG_ROOT chain=$CHAIN allow=lo:{$BROKER_PORT,$PROXY_PORT} (verified)"
