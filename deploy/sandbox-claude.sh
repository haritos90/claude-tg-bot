#!/bin/bash
# Bubblewrap launcher for a sandboxed code-session `claude`.
# - SDK invokes it as `cli_path` with cwd = workdir
# - `engine._enable_sandbox` sets the SBX_* env read below
# - drops uid; only workdir and tmpfs HOME are writable
# - network kept; bot env wiped via `--clearenv`
# - agent's Bash can read injected token unless broker mode
set -euo pipefail

WORKDIR="$PWD"
SUID="${SBX_UID:-65534}"
SGID="${SBX_GID:-65534}"
CLAUDE="${SBX_CLAUDE:-/root/.local/bin/claude}"
CREDS="${SBX_CREDS:-$HOME/.claude/.credentials.json}"
# `SBX_EXEC` is reserved; execution is always permitted.
# - bwrap 0.8 has no per-bind noexec flag
# - code mode needs to run tools

# Credential goes onto fd 9 before dropping privileges.
# - bwrap injects its content into the jail's tmpfs
# - broker mode: dummy token plus `ANTHROPIC_BASE_URL` to broker
# - dummy token has far-future expiry; CLI never refreshes it
# - without `SBX_BROKER_URL`, the real creds are bound
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
# Under a per-session uid, `/root` is unreachable (0700).
# - the bot stages the claude binary under `/usr`
# - `SBX_CLAUDE` points there; skip the `/root` bind
[ -z "${SBX_HOST_UID:-}" ] && [ -d /root/.local ] && args+=(--ro-bind /root/.local /root/.local)
[ -d /sbin ]  && args+=(--ro-bind /sbin /sbin)

# Forward the auto-compaction kill-switch into the jail when set.
# - `--clearenv` wipes the bot's env for the inner CLI
# - absent means autocompact stays on
[ -n "${DISABLE_AUTO_COMPACT:-}" ] && args+=(--setenv DISABLE_AUTO_COMPACT "$DISABLE_AUTO_COMPACT")

# Forward plain engine/SDK protocol flags that `--clearenv` would drop.
# - SDK's own markers
# - session-state stream tells folded follow-ups from new turns
# - the engine's Workflows kill-switch
# - explicit allowlist, never a pattern that could carry a token
for _v in CLAUDE_CODE_ENTRYPOINT CLAUDE_AGENT_SDK_VERSION CLAUDE_CODE_SDK_READS_SESSION_STATE \
          CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS CLAUDE_CODE_DISABLE_WORKFLOWS \
          CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING; do
  [ -n "${!_v:-}" ] && args+=(--setenv "$_v" "${!_v}")
done

# Broker mode points the inner CLI at the loopback broker.
# - jail shares the host netns, so 127.0.0.1 reaches it
# - real OAuth token is injected there, not in jail
[ -n "${SBX_BROKER_URL:-}" ] && args+=(--setenv ANTHROPIC_BASE_URL "$SBX_BROKER_URL")

# Egress-allowlist mode routes dev tools through the host CONNECT proxy.
# - firewall drops non-loopback exits; proxy is the only way out
# - `NO_PROXY` exempts loopback so broker calls skip the proxy
if [ -n "${SBX_PROXY_URL:-}" ]; then
  _np="${SBX_NO_PROXY:-127.0.0.1,localhost,::1}"
  args+=(--setenv HTTPS_PROXY "$SBX_PROXY_URL" --setenv https_proxy "$SBX_PROXY_URL"
         --setenv HTTP_PROXY "$SBX_PROXY_URL"  --setenv http_proxy "$SBX_PROXY_URL"
         --setenv NO_PROXY "$_np" --setenv no_proxy "$_np")
fi

# Inject this session's user-supplied service credentials as env vars.
# - scoped to this jail only (per-session root-owned 0600 file)
# - the owner's own credentials never enter any jail
if [ -n "${SBX_SECRETS_ENV:-}" ] && [ -f "$SBX_SECRETS_ENV" ]; then
  while IFS= read -r _line || [ -n "$_line" ]; do
    case "$_line" in ''|'#'*) continue;; esac
    _k="${_line%%=*}"; _v="${_line#*=}"
    [[ "$_k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    args+=(--setenv "$_k" "$_v")
  done < "$SBX_SECRETS_ENV"
fi

# Load a seccomp denylist to shrink kernel attack surface.
# - bwrap reads the BPF program from an fd
# - the fd must stay open across exec
if [ -n "${SBX_SECCOMP:-}" ] && [ -f "$SBX_SECCOMP" ]; then
  exec 8<"$SBX_SECCOMP"
  args+=(--seccomp 8)
fi

# DNS: bind the real resolv.conf target for /run symlinks.
# - systemd-resolved symlink must resolve inside the jail
# - otherwise claude fails with FailedToOpenSocket
RESOLV="$(readlink -f /etc/resolv.conf 2>/dev/null || true)"
if [ -n "$RESOLV" ] && [ "$RESOLV" != "/etc/resolv.conf" ] && [ -f "$RESOLV" ]; then
  args+=(--ro-bind "$RESOLV" "$RESOLV")
fi

# Persist claude's session state across rebuilds and restarts.
# - bind a per-session host dir at the jail's `~/.claude/projects`
# - so `resume` survives
# - rest of HOME, incl. credential overlay, stays ephemeral
if [ -n "${SBX_STATE:-}" ] && [ -d "$SBX_STATE" ]; then
  args+=(--bind "$SBX_STATE" /home/sbx/.claude/projects)
fi

# Make the jail root read-only after binds are set up.
# - bwrap's implicit root is a writable tmpfs
# - stray absolute-path writes would silently vanish into it
# - read-only makes them fail loudly; the agent retries in cwd
# - workdir, /tmp, /home/sbx and `SBX_STATE` stay writable
args+=(--remount-ro /)

# Tighten the umask so agent outputs are owner-only.
# - 0600 files, 0700 dirs; inherited across exec
# - root bot still reads them (root bypasses the mode)
# - pairs with host-side chmod 0700 on the workdir
umask 077

# Cap the process count to blunt fork-bomb DoS.
# - per-uid, so shared across concurrent sandboxed sessions
ulimit -u 512 2>/dev/null || true

# Place this launcher into a dedicated cgroup leaf.
# - it becomes bwrap after exec, so claude inherits the cgroup
# - the egress firewall matches jail traffic by this cgroup
# - the leaf carries per-jail mem/CPU/pid limits
# - joined by hand: `systemd-run` would orphan claude on SIGKILL
if [ -n "${SBX_USE_CGROUP:-}" ]; then
  _cgroot="${SBX_CGROUP:-/sys/fs/cgroup/sbx}"
  _leaf="$_cgroot/$$"
  if [ -d "$_cgroot" ] && mkdir -p "$_leaf" 2>/dev/null; then
    [ -n "${SBX_MEM_MAX:-}" ]  && { echo "$SBX_MEM_MAX"  > "$_leaf/memory.max" 2>/dev/null || true; }
    [ -n "${SBX_PIDS_MAX:-}" ] && { echo "$SBX_PIDS_MAX" > "$_leaf/pids.max"   2>/dev/null || true; }
    [ -n "${SBX_CPU_MAX:-}" ]  && { echo "$SBX_CPU_MAX"  > "$_leaf/cpu.max"    2>/dev/null || true; }
    if ! echo $$ > "$_leaf/cgroup.procs" 2>/dev/null; then
      echo "sandbox: failed to join cgroup $_leaf" >&2
      # Egress on but outside the matched cgroup means full egress.
      # - fail-open hole, so refuse
      # - limits-only: a lost limit is acceptable, so proceed
      if [ "${SBX_EGRESS:-}" = "1" ]; then exit 1; fi
    fi
  else
    echo "sandbox: cgroup $_cgroot unavailable" >&2
    if [ "${SBX_EGRESS:-}" = "1" ]; then exit 1; fi
  fi
fi

# Run bwrap as a distinct non-root host uid.
# - a userns/kernel escape lands unprivileged
# - cannot read other sessions' files (other uid, mode 0700)
# - writable trees are chowned once; skipped when already correct
# - `setpriv` execs without fork; cgroup and open fds survive

# Shell mode execs a one-shot bash command in the jail.
# - all SBX_* isolation above is target-agnostic and already applied
# - `SBX_SHELL_CMD` is the command line
if [ "${SBX_MODE:-}" = "shell" ]; then
  CLAUDE="/bin/bash"
  set -- -lc "${SBX_SHELL_CMD:-true}"
fi

# Persistent shell: interactive non-login bash on the host PTY.
# - stdin/stdout/stderr are the pty slave
# - host drives it line-by-line so cd/env persist
# - same SBX_* isolation; only the target differs
if [ "${SBX_MODE:-}" = "shell_persist" ]; then
  CLAUDE="/bin/bash"
  set -- -i
fi

if [ -n "${SBX_HOST_UID:-}" ]; then
  _huid="$SBX_HOST_UID"; _hgid="${SBX_HOST_GID:-$SBX_HOST_UID}"
  # The per-session parent dir stays root-owned but must be traversable.
  # - session uid needs to reach its own `work/` (0700)
  # - 0711 means traverse, not list
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
