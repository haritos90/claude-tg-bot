"""Cold storage for deleted sessions.

- Deleted sessions are bundled into one gzip tarball
- Bundles live under `BASE_WORKDIR/_archive/<owner_id>/`
- Footprint: `BASE_WORKDIR/<sid>/` plus legacy `~/.claude/projects/<encoded>`
- Best-effort and fail-safe: live copies stay on write error
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import re
import shutil
import tarfile
import time
from pathlib import Path

log = logging.getLogger("archive")

# Archive root, relative to `BASE_WORKDIR`.
# - Leading underscore never collides with hex sids
ARCHIVE_DIRNAME = "_archive"


def encode_workdir(workdir: str | Path) -> str:
    """Claude Code project-dir name for a working directory.

    - Replaces every non-alphanumeric character with `-`
    - Single shared encoder; never use plain `replace('/', '-')`
    - A divergent encoder breaks cwds containing `.` or `_`
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(workdir)))


def live_transcript_dir(cwd: str | Path) -> Path:
    """Live transcript dir of a jailed session for a cwd.

    - Path is `<sid>/state/<encoded-cwd>`
    """
    cwd = Path(cwd)
    return cwd.parent / "state" / encode_workdir(cwd)


def transcript_dir(workdir: str | Path, claude_home: Path | None = None) -> Path:
    """Transcript project directory for a working directory.

    - Named via `encode_workdir`
    """
    home = claude_home or (Path.home() / ".claude")
    return home / "projects" / encode_workdir(workdir)


def _dir_size(path: Path) -> int:
    """Total bytes under a path; 0 on any error."""
    total = 0
    with contextlib.suppress(OSError):
        for p in path.rglob("*"):
            with contextlib.suppress(OSError):
                if p.is_file():
                    total += p.stat().st_size
    return total


def archive_session(
    base_workdir: str | Path,
    sid: str,
    *,
    owner_id: int,
    key: int | None = None,
    name: str | None = None,
    claude_home: Path | None = None,
    stamp: str | None = None,
) -> Path | None:
    """Archive a deleted session into one tar.gz bundle.

    - Bundle goes under `BASE_WORKDIR/_archive/<owner_id>/`
    - Returns bundle path, or `None` if nothing to archive
    - Transcript touched only when its name ends with sid
    - On write failure, partial bundle removed, live copies kept
    """
    base = Path(base_workdir)
    # Whole per-session dir (`work/` plus `state/`) is one bundle.
    session_dir = base / sid
    tdir = transcript_dir(session_dir, claude_home)

    # (arcname in bundle, live path) for each existing piece.
    sources: list[tuple[str, Path]] = []
    if session_dir.is_dir():
        sources.append(("session", session_dir))
    # Legacy host transcript for non-sandboxed sessions.
    # - Only this session's dir (name ends with sid)
    # - Never the shared repo-root projects dir
    if tdir.is_dir() and tdir.name.endswith(sid):
        sources.append(("transcript", tdir))

    if not sources:
        return None

    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    arch_root = base / ARCHIVE_DIRNAME / str(owner_id)
    arch_root.mkdir(parents=True, exist_ok=True)
    bundle = arch_root / f"{sid}-{stamp}.tar.gz"

    meta = {
        "sid": sid,
        "key": key,
        "owner_id": owner_id,
        "name": name,
        "deleted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stamp": stamp,
        "parts": [
            {"arcname": arc, "path": str(p), "bytes": _dir_size(p)}
            for arc, p in sources
        ],
    }

    try:
        with tarfile.open(bundle, "w:gz") as tf:
            for arcname, path in sources:
                tf.add(path, arcname=arcname)
            data = json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")
            info = tarfile.TarInfo("meta.json")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    except Exception:
        log.exception("archive_session: failed to write bundle %s — keeping live copies", bundle)
        with contextlib.suppress(OSError):
            bundle.unlink()
        return None

    # Sidecar meta lets an archive browser list without untarring.
    with contextlib.suppress(Exception):
        (arch_root / f"{sid}-{stamp}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # Bundle is safely on disk; free live space.
    for _arc, path in sources:
        shutil.rmtree(path, ignore_errors=True)

    log.info(
        "archived session sid=%s key=%s owner=%s → %s (%d part(s))",
        sid, key, owner_id, bundle, len(sources),
    )
    return bundle


def purge_expired(
    base_workdir: str | Path,
    max_age_days: float,
    *,
    now: float | None = None,
) -> tuple[int, int]:
    """Delete archived bundles older than `max_age_days`.

    - Removes each bundle and its `*.json` sidecar
    - Returns `(bundles_removed, bytes_freed)`
    - Non-positive `max_age_days` keeps forever (no-op)
    - Fail-soft; age by mtime, per-file errors swallowed
    """
    if not max_age_days or max_age_days <= 0:
        return (0, 0)
    root = Path(base_workdir) / ARCHIVE_DIRNAME
    if not root.is_dir():
        return (0, 0)
    cutoff = (now if now is not None else time.time()) - float(max_age_days) * 86400.0
    removed = 0
    freed = 0
    for bundle in sorted(root.rglob("*.tar.gz")):
        try:
            if not bundle.is_file() or bundle.stat().st_mtime >= cutoff:
                continue
            freed += bundle.stat().st_size
            bundle.unlink()
            removed += 1
        except OSError:
            continue
        # Drop the matching sidecar meta, best effort.
        sidecar = bundle.parent / (bundle.name[: -len(".tar.gz")] + ".json")
        with contextlib.suppress(OSError):
            sidecar.unlink()
    if removed:
        log.info(
            "archive purge: removed %d bundle(s), freed %d bytes (retention %s d)",
            removed, freed, max_age_days,
        )
    return (removed, freed)
