#!/bin/bash
# deploy/egress-setup.sh — host-side egress allowlist for the sandbox (#119c).
#
# Confines the jail's network egress to LOOPBACK ONLY (the credential broker #119b +
# the egress proxy #119c), dropping every other destination — so a jailed agent can
# reach Anthropic (via the broker) and chosen dev hosts (via the proxy) but cannot POST
# the owner's data to an arbitrary host. Combined with the broker (token never in the
# jail) this closes the exfil channels the bwrap FS confinement (#104) left open.
#
# SAFETY — this is the live-VPS lockout-risk piece, engineered to be unlockoutable:
#   * It NEVER touches the OUTPUT policy or any existing chain. It creates ONE dedicated
#     chain (SBX_EGRESS) and ONE jump into OUTPUT that fires ONLY for the sandbox cgroup
#     (`-m cgroup --path sbx`). SSH, the bot, Docker, everything else is never matched.
#   * Match is by CGROUP, not uid: the jail runs `--unshare-user --uid 65534`, so from
#     the host the socket's owner is outer-root and an `--uid` match would miss — the
#     launcher puts the jail in /sys/fs/cgroup/sbx/<pid> and we match that.
#   * Fully reverted by deploy/egress-teardown.sh (`-D` the jump, `-F`/`-X` the chain).
#
# Idempotent. Args: [broker_port] [proxy_port]  (defaults 8789 / 8790).
set -euo pipefail

CG_ROOT="${SBX_CGROUP:-/sys/fs/cgroup/sbx}"
CG_NAME="$(basename "$CG_ROOT")"        # iptables --path is relative to the cgroup2 root
CHAIN="SBX_EGRESS"
BROKER_PORT="${1:-8789}"
PROXY_PORT="${2:-8790}"

# The cgroup match lives in xt_cgroup; load it (iptables won't always auto-load it).
modprobe xt_cgroup 2>/dev/null || true

# 1) The cgroup the launcher joins: membership = both the firewall match (this file)
#    and the per-jail resource container (#119e). Enable the memory/pids/cpu controllers
#    on its subtree so leaves can set limits; egress itself needs only membership, so a
#    controller-enable failure is non-fatal.
mkdir -p "$CG_ROOT"
PARENT_CTRL="$(dirname "$CG_ROOT")/cgroup.controllers"
for c in memory pids cpu; do
  if grep -qw "$c" "$PARENT_CTRL" 2>/dev/null; then
    echo "+$c" > "$CG_ROOT/cgroup.subtree_control" 2>/dev/null || true
  fi
done
# Sweep stale empty leaves left by previous runs (a leaf has no post-exit cleanup hook).
for d in "$CG_ROOT"/*/; do
  [ -d "$d" ] || continue
  if [ ! -s "$d/cgroup.procs" ]; then rmdir "$d" 2>/dev/null || true; fi
done

# 2) The egress chain + the cgroup-scoped jump, for both IPv4 and IPv6.
#    IPv4: allow loopback to the broker + proxy ports; reject the rest.
#    IPv6: no v6 broker/proxy, so reject ALL v6 egress from the cgroup (closes a bypass).
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

echo "[egress-setup] cgroup=$CG_ROOT chain=$CHAIN allow=lo:{$BROKER_PORT,$PROXY_PORT}"
