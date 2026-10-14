"""Keep the Claude Code CLI current.

- `update_and_stage` runs `claude update`, then `stage`
- `stage` copies the CLI to `STAGED_PATH` for jails
- Jail uid cannot read ~/.local, hence the copy
- Copy is atomic via temp file and `os.replace`
- Blocking: call through `asyncio.to_thread`
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
    """Host CLI's resolved path, or None if absent.

    - `~/.local/bin/claude` symlinks into a versioned directory
    """
    path = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    if not path or not os.path.exists(path):
        return None
    return os.path.realpath(path)


def version_of(path: str | None) -> str:
    """CLI version at `path`, or empty if unknown.

    - Parsed from file name, else `--version`
    """
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
    """Host CLI path the staged copy came from.

    - Empty string when never staged
    """
    try:
        with open(dst + ".src", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def stage(dst: str = STAGED_PATH) -> str | None:
    """Copy host CLI to `dst` if its path changed.

    - Also copies when `dst` is missing
    - Returns source path if copied, else None
    """
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
    """Run `claude update`; return (succeeded, last output line).

    - Never raises
    - API-key variables are stripped (subscription only)
    """
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
    except Exception as exc:  # updater errors must not escape
        return False, f"{type(exc).__name__}: {exc}"
    lines = [ln.strip() for ln in ((r.stdout or "") + "\n" + (r.stderr or "")).splitlines()
             if ln.strip()]
    return r.returncode == 0, (lines[-1] if lines else f"exit {r.returncode}")[:300]


@dataclass
class UpdateResult:
    ok: bool          # updater exited cleanly
    before: str       # host version before run
    after: str        # host version after run
    staged: bool      # jail copy was refreshed
    detail: str       # updater's last output line

    @property
    def changed(self) -> bool:
        return bool(self.after) and self.after != self.before


def update_and_stage(stage_jail: bool = True) -> UpdateResult:
    """Run one update round, then re-stage jail copy.

    - Staging runs even if the updater failed
    - Covers a host CLI updated by other means
    """
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
