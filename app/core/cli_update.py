"""Keep the Claude Code CLI current (#412).

A model release needs a CLI that knows the new model (its id and request shape), and the
bot takes its model list from the CLI itself (``app/core/models.py``) — so the bot keeps the
CLI current on its own instead of waiting for a manual update + restart:

* :func:`update_and_stage` runs the host CLI's own updater (``claude update``), then
  :func:`stage`;
* :func:`stage` copies the host CLI to :data:`STAGED_PATH` — the binary a jail running under
  a per-session NON-ROOT uid execs, since it cannot reach ``~/.local`` (``/root`` is 0700) —
  whenever the host CLI's resolved version path changed since the last copy (a marker file
  records it). The copy goes through a temp file + ``os.replace``, so a jail starting at that
  moment execs either the old or the new binary, never a half-written one, and a running
  client keeps the inode it started with until the reaper frees it.

``SessionManager.start_cli_updater`` runs it once a day at ``CLI_UPDATE_AT_UTC`` (default 12:00
UTC, owner-adjustable in /settings → Admin, "off" = never — #423; was the
``CLI_UPDATE_INTERVAL_HOURS`` cadence) and then recycles idle clients onto the new binary.
Everything here BLOCKS (subprocess + file copy) — call it through ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("cli_update")

STAGED_PATH = "/usr/local/bin/claude"
_VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
_UPDATE_TIMEOUT_SEC = 600


def host_cli() -> str | None:
    """The host CLI's RESOLVED path (``~/.local/bin/claude`` is a symlink into
    ``~/.local/share/claude/versions/<ver>``), or None when no CLI is installed."""
    path = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    if not path or not os.path.exists(path):
        return None
    return os.path.realpath(path)


def version_of(path: str | None) -> str:
    """The CLI version at ``path`` — from the versioned file name when it carries one, else
    from ``<path> --version``; "" when unknown."""
    if not path:
        return ""
    m = _VERSION_RE.search(os.path.basename(path))
    if m:
        return m.group(0)
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True,
                             timeout=30, stdin=subprocess.DEVNULL).stdout
    except Exception:
        return ""
    m = _VERSION_RE.search(out or "")
    return m.group(0) if m else ""


def staged_source(dst: str = STAGED_PATH) -> str:
    """The host CLI path the staged copy was taken from ("" when never staged)."""
    try:
        with open(dst + ".src", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def stage(dst: str = STAGED_PATH) -> str | None:
    """Copy the host CLI to ``dst`` when its resolved path changed since the last copy (or
    ``dst`` is missing). Returns the source path when it copied, None when nothing changed."""
    src = host_cli()
    if not src:
        return None
    if staged_source(dst) == src and os.path.exists(dst):
        return None
    tmp = dst + ".tmp"
    shutil.copy2(src, tmp)
    os.chmod(tmp, 0o755)
    os.replace(tmp, dst)
    with open(dst + ".src", "w", encoding="utf-8") as fh:
        fh.write(src)
    logger.info("Staged sandbox claude binary at %s (from %s)", dst, src)
    return src


def run_update(timeout: float = _UPDATE_TIMEOUT_SEC) -> tuple[bool, str]:
    """Run ``claude update`` (the CLI's own installer/updater — it only swaps the versioned
    binary + symlink). Returns (succeeded, last output line). Never raises. The API-key
    variables are stripped like for every spawned CLI (subscription only)."""
    exe = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    if not exe or not os.path.exists(exe):
        return False, "claude CLI not found"
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    try:
        r = subprocess.run([exe, "update"], env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {int(timeout)}s"
    except Exception as exc:  # never let an updater hiccup escape into the loop
        return False, f"{type(exc).__name__}: {exc}"
    lines = [ln.strip() for ln in ((r.stdout or "") + "\n" + (r.stderr or "")).splitlines()
             if ln.strip()]
    return r.returncode == 0, (lines[-1] if lines else f"exit {r.returncode}")[:300]


@dataclass
class UpdateResult:
    ok: bool          # the updater exited cleanly
    before: str       # host CLI version before the run
    after: str        # host CLI version after the run
    staged: bool      # the jail copy was refreshed
    detail: str       # the updater's last output line

    @property
    def changed(self) -> bool:
        return bool(self.after) and self.after != self.before


def update_and_stage(stage_jail: bool = True) -> UpdateResult:
    """One update round: ``claude update``, then re-stage the jail copy (when the jail uses
    one). The stage step runs even when the updater failed, so a host CLI updated by other
    means (an interactive ``claude`` session auto-updating) still reaches the jails."""
    before = version_of(host_cli())
    ok, detail = run_update()
    after = version_of(host_cli())
    staged = False
    if stage_jail:
        try:
            staged = stage() is not None
        except Exception:
            logger.warning("re-staging the sandbox claude binary failed", exc_info=True)
    return UpdateResult(ok=ok, before=before, after=after, staged=staged, detail=detail)
