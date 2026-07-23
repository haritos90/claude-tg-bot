#!/bin/bash
# deploy/sandbox-claude.sh — bubblewrap launcher for a sandboxed code-session
# `claude` (#104). The SDK invokes this as ClaudeAgentOptions.cli_path with cwd =
# the session workdir; engine._enable_sandbox sets the SBX_* env read below.
#
# It drops to an unprivileged uid, confines the filesystem to the session workdir
# (the only writable host path) + a private tmpfs HOME, injects the subscription
# credential READ-ONLY into the jail (ephemeral tmpfs, never a reachable host
# path), keeps the network (claude must reach Anthropic), and execs the real CLI.
# The bot's env (TELEGRAM_BOT_TOKEN, …) is wiped via --clearenv.
#
# Session state persists (#115): the HOME is a private tmpfs, but ~/.claude/projects
# is bind-mounted from a per-session host dir (SBX_STATE), so claude's `resume`
# survives a client rebuild / bot restart. The credential stays ephemeral (a tmpfs
# overlay); the rest of HOME is throwaway.
#
# Residual P0 (owner-deferred): the agent's own Bash shares this process, so it CAN
# read the injected token — it simply cannot ESCAPE the workdir or touch the host /
# other sessions. Blocking exfiltration (a network egress allowlist) is a later phase.
set -euo pipefail

WORKDIR="$PWD"
SUID="${SBX_UID:-65534}"
SGID="${SBX_GID:-65534}"
CLAUDE="${SBX_CLAUDE:-/root/.local/bin/claude}"
CREDS="${SBX_CREDS:-$HOME/.claude/.credentials.json}"
# SBX_EXEC ("1" = perm 7 / exec ok, "0" = perm 6 / noexec) is reserved: bwrap 0.8
# has no per-bind noexec flag and code mode generally needs to run tools, so v1
# always permits execution (a future refinement).

# Credential onto fd 9 BEFORE dropping privileges; bwrap injects its CONTENT into the
# jail's tmpfs (never a reachable host path).
# #119b broker mode (SBX_BROKER_URL set): the jail gets a DUMMY token + an
# ANTHROPIC_BASE_URL pointing at the host credential broker, which swaps in the REAL
# OAuth bearer — so the subscription token is NEVER inside the jail. The dummy carries a
# far-future expiry so the inner CLI never tries to refresh it (a refresh would hit the
# real OAuth host with a bogus token). Without SBX_BROKER_URL, bind the real creds.
if [ -n "${SBX_BROKER_URL:-}" ]; then
  DUMMY_CREDS="$(mktemp)"
  printf '{"claudeAiOauth":{"accessToken":"BROKER-PLACEHOLDER","refreshToken":"BROKER-PLACEHOLDER","expiresAt":%s000,"scopes":["user:inference","user:profile"],"subscriptionType":"max"}}' \
    "$(( $(date +%s) + 31536000 ))" > "$DUMMY_CREDS"
  exec 9<"$DUMMY_CREDS"
  rm -f "$DUMMY_CREDS"   # fd 9 stays valid after unlink; nothing real ever on disk
else
  exec 9<"$CREDS"
fi

args=(
  --unshare-user --uid "$SUID" --gid "$SGID"
  --clearenv
  --setenv HOME /home/sbx
  --setenv PATH /usr/bin:/bin
  --setenv LANG "${LANG:-C.UTF-8}"
  --setenv TERM "${TERM:-xterm}"
  --ro-bind /usr /usr
  --ro-bind /bin /bin
  --ro-bind /etc /etc
  --proc /proc --dev /dev --tmpfs /tmp
  --tmpfs /home/sbx
  --dir /home/sbx/.claude
  --ro-bind-data 9 /home/sbx/.claude/.credentials.json
  --bind "$WORKDIR" "$WORKDIR"
  --unshare-pid --unshare-ipc --unshare-uts
  --die-with-parent
  --chdir "$WORKDIR"
)
[ -d /lib ]   && args+=(--ro-bind /lib /lib)
[ -d /lib64 ] && args+=(--ro-bind /lib64 /lib64)
# The claude CLI lives under /root/.local (root's home). The default root-mapped jail
# binds it directly; under a per-session unprivileged uid (#119) /root is unreachable
# (0700), so the bot stages the binary world-readably under /usr (bound above) and
# SBX_CLAUDE points there — skip the /root bind in that mode.
[ -z "${SBX_HOST_UID:-}" ] && [ -d /root/.local ] && args+=(--ro-bind /root/.local /root/.local)
[ -d /sbin ]  && args+=(--ro-bind /sbin /sbin)

# #168: forward the auto-compaction kill-switch into the jail when the engine set it.
# The bot's env reaches THIS launcher, but --clearenv wipes it for the inner CLI, so
# it must be re-injected explicitly. Absent → autocompact stays ON (the CLI default).
[ -n "${DISABLE_AUTO_COMPACT:-}" ] && args+=(--setenv DISABLE_AUTO_COMPACT "$DISABLE_AUTO_COMPACT")

# #119b: in broker mode, point the inner CLI at the host credential broker (loopback).
# The jail shares the host network namespace, so 127.0.0.1 reaches the broker; the real
# OAuth token is injected there, never inside the jail.
[ -n "${SBX_BROKER_URL:-}" ] && args+=(--setenv ANTHROPIC_BASE_URL "$SBX_BROKER_URL")

# #119c: egress-allowlist mode — route the agent's dev tools (git/pip/npm/curl) through
# the host CONNECT proxy (HTTPS_PROXY). The cgroup firewall (egress-setup.sh) drops every
# non-loopback exit, so the proxy is the ONLY way out for external hosts. NO_PROXY exempts
# loopback so the broker call (ANTHROPIC_BASE_URL=127.0.0.1) does not loop through it.
if [ -n "${SBX_PROXY_URL:-}" ]; then
  _np="${SBX_NO_PROXY:-127.0.0.1,localhost,::1}"
  args+=(--setenv HTTPS_PROXY "$SBX_PROXY_URL" --setenv https_proxy "$SBX_PROXY_URL"
         --setenv HTTP_PROXY "$SBX_PROXY_URL"  --setenv http_proxy "$SBX_PROXY_URL"
         --setenv NO_PROXY "$_np" --setenv no_proxy "$_np")
fi

# #119d: inject this session's user-supplied service credentials (e.g. a GitHub token)
# as env vars — scoped to THIS jail only (the file is per-session + root-owned 0600). The
# owner's own credentials NEVER enter any jail; a user leaking their own is their problem.
if [ -n "${SBX_SECRETS_ENV:-}" ] && [ -f "$SBX_SECRETS_ENV" ]; then
  while IFS= read -r _line || [ -n "$_line" ]; do
    case "$_line" in ''|'#'*) continue;; esac
    _k="${_line%%=*}"; _v="${_line#*=}"
    [[ "$_k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    args+=(--setenv "$_k" "$_v")
  done < "$SBX_SECRETS_ENV"
fi

# #119e: load a seccomp denylist (deploy/make-seccomp.py) to shrink the kernel attack
# surface. bwrap reads the BPF program from the fd, which must stay open across exec.
if [ -n "${SBX_SECCOMP:-}" ] && [ -f "$SBX_SECCOMP" ]; then
  exec 8<"$SBX_SECCOMP"
  args+=(--seccomp 8)
fi

# DNS: when /etc/resolv.conf is a systemd-resolved symlink into /run, bind the
# real target at its own path so the symlink resolves inside the jail (otherwise
# claude can't reach the API — "FailedToOpenSocket").
RESOLV="$(readlink -f /etc/resolv.conf 2>/dev/null || true)"
if [ -n "$RESOLV" ] && [ "$RESOLV" != "/etc/resolv.conf" ] && [ -f "$RESOLV" ]; then
  args+=(--ro-bind "$RESOLV" "$RESOLV")
fi

# Persist claude's session state across rebuilds/restarts (#115): bind a per-session
# host dir at the jail's ~/.claude/projects so `resume` survives. The rest of HOME
# (incl. the credential overlay) stays ephemeral tmpfs.
if [ -n "${SBX_STATE:-}" ] && [ -d "$SBX_STATE" ]; then
  args+=(--bind "$SBX_STATE" /home/sbx/.claude/projects)
fi

# #136: make the jail ROOT read-only AFTER all binds are set up. bwrap's implicit
# root is a writable tmpfs, so an agent writing to a stray absolute path it imagined
# (e.g. /Users/<name>, ~/foo resolved oddly) "succeeded" into throwaway jail space —
# the file then vanished and was invisible to /files & export ("why didn't it write
# to the workdir?"). With the root read-only, such writes FAIL LOUDLY ("Read-only
# file system") and the agent retries in the cwd. The workdir bind, /tmp, /home/sbx
# tmpfs and SBX_STATE bind stay writable (they were mounted before this remount).
args+=(--remount-ro /)

# #137: tighten the file-creation mask so the agent's outputs (written as the
# unprivileged uid) are owner-only — 0600 files / 0700 dirs — not world/group
# readable. Inherited across exec into the jailed process. The bot (root) still
# reads them for /files + export (root bypasses the mode); other LOCAL non-root
# users no longer can. Pair with the host-side chmod 0700 on the workdir (engine).
umask 077

# Resource limit (#116): cap the process count to blunt a fork-bomb DoS from
# sandboxed code (per-uid, so shared across concurrent sandboxed sessions).
ulimit -u 512 2>/dev/null || true

# #119c/#119e: place this launcher — which BECOMES bwrap after exec, so claude inherits
# the cgroup — into a dedicated cgroup leaf. Membership does double duty: the host egress
# firewall matches the jail's traffic by this cgroup (deploy/egress-setup.sh), and the
# leaf carries the per-jail mem/CPU/pid limits. Done BY HAND, not `systemd-run --scope`:
# that forks the target under PID 1, so a SIGKILL on the SDK's child would orphan the
# ~500 MB claude (defeating the idle reaper, #179). Here the tree stays
# SDK→launcher/bwrap→claude, so the existing kill path still reaps it.
if [ -n "${SBX_USE_CGROUP:-}" ]; then
  _cgroot="${SBX_CGROUP:-/sys/fs/cgroup/sbx}"
  _leaf="$_cgroot/$$"
  if [ -d "$_cgroot" ] && mkdir -p "$_leaf" 2>/dev/null; then
    [ -n "${SBX_MEM_MAX:-}" ]  && { echo "$SBX_MEM_MAX"  > "$_leaf/memory.max" 2>/dev/null || true; }
    [ -n "${SBX_PIDS_MAX:-}" ] && { echo "$SBX_PIDS_MAX" > "$_leaf/pids.max"   2>/dev/null || true; }
    [ -n "${SBX_CPU_MAX:-}" ]  && { echo "$SBX_CPU_MAX"  > "$_leaf/cpu.max"    2>/dev/null || true; }
    if ! echo $$ > "$_leaf/cgroup.procs" 2>/dev/null; then
      echo "sandbox: failed to join cgroup $_leaf" >&2
      # Egress ON + not in the matched cgroup = FULL egress (fail-open hole) → refuse.
      # Limits-only → a lost limit is acceptable, so proceed.
      if [ "${SBX_EGRESS:-}" = "1" ]; then exit 1; fi
    fi
  else
    echo "sandbox: cgroup $_cgroot unavailable" >&2
    if [ "${SBX_EGRESS:-}" = "1" ]; then exit 1; fi
  fi
fi

# #119: per-session unprivileged HOST uid (escape hardening). Run bwrap — and thus the
# inner claude — as a DISTINCT non-root host uid, so a userns/kernel escape lands as an
# unprivileged user (not host root) AND cannot read another session's files (owned by a
# different uid, mode 0700). The session's writable trees are chowned to that uid once
# (skipped when already correct), then we drop with `setpriv`, which EXECs (no fork — the
# process tree + the cgroup membership set above stay intact, so the reaper still works).
# The credential fd 9 and seccomp fd were opened as root above and survive the drop.

# #224: shell mode — swap the exec target to a ONE-SHOT bash command in the jail. All the
# SBX_* isolation above (uid, egress allowlist, secrets, cgroup, seccomp) is target-agnostic
# and already applied; only the final exec target changes. SBX_SHELL_CMD is the command line.
if [ "${SBX_MODE:-}" = "shell" ]; then
  CLAUDE="/bin/bash"
  set -- -lc "${SBX_SHELL_CMD:-true}"
fi

# #227a: persistent shell — exec an INTERACTIVE bash (`-i`, non-login) that reads from the PTY the host
# holds (its stdin/stdout/stderr are the pty slave). The host drives it line-by-line so cd/env
# persist across messages. Same SBX_* isolation as above (target-agnostic); only the target.
if [ "${SBX_MODE:-}" = "shell_persist" ]; then
  CLAUDE="/bin/bash"
  set -- -i
fi

if [ -n "${SBX_HOST_UID:-}" ]; then
  _huid="$SBX_HOST_UID"; _hgid="${SBX_HOST_GID:-$SBX_HOST_UID}"
  # The per-session parent (<sid>/) stays root-owned but must be TRAVERSABLE by the
  # session uid so it can reach its own work/ (0700). 0711 = traverse, not list.
  chmod 0711 "$(dirname "$WORKDIR")" 2>/dev/null || true
  if [ "$(stat -c %u "$WORKDIR" 2>/dev/null || echo -1)" != "$_huid" ]; then
    chown -R "$_huid:$_hgid" "$WORKDIR" 2>/dev/null || true
  fi
  if [ -n "${SBX_STATE:-}" ] && [ -d "$SBX_STATE" ] \
     && [ "$(stat -c %u "$SBX_STATE" 2>/dev/null || echo -1)" != "$_huid" ]; then
    chown -R "$_huid:$_hgid" "$SBX_STATE" 2>/dev/null || true
  fi
  exec setpriv --reuid "$_huid" --regid "$_hgid" --clear-groups \
    bwrap "${args[@]}" "$CLAUDE" "$@"
fi

exec bwrap "${args[@]}" "$CLAUDE" "$@"
