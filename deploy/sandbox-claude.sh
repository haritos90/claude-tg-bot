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
# always permits execution (documented in CLAUDE.md as a future refinement).

# Read the root-only (0600) credential onto fd 9 BEFORE dropping privileges; bwrap
# injects its CONTENT into the jail's tmpfs (never a reachable host path).
exec 9<"$CREDS"

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
  --ro-bind /root/.local /root/.local
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
[ -d /sbin ]  && args+=(--ro-bind /sbin /sbin)

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

# Resource limit (#116): cap the process count to blunt a fork-bomb DoS from
# sandboxed code (per-uid, so shared across concurrent sandboxed sessions).
ulimit -u 512 2>/dev/null || true

exec bwrap "${args[@]}" "$CLAUDE" "$@"
