"""Cold storage for deleted sessions (#177).

When a user deletes a DM session we no longer DESTROY its data (the old #58/#136
path `shutil.rmtree`-d the workdir outright). Instead we MOVE everything into a
single gzip-compressed bundle under ``BASE_WORKDIR/_archive/<owner_id>/`` so disk
use drops (text/jsonl transcripts compress ~10×) while nothing is lost. Deleting
the archives themselves (retention / auto-purge) is deliberately NOT wired yet —
that's the deferred #178.

Since #180/#181 every session is JAILED and uses a NESTED layout, so a session's
footprint is ONE parent dir (plus a legacy fallback):

  1. ``BASE_WORKDIR/<sid>/``  — the whole session: ``work/`` (the agent's cwd /
     files) + ``state/`` (the jail HOME → ``~/.claude/projects``, i.e. the
     transcript). Bundling this one dir captures everything for a jailed session.
  2. ``~/.claude/projects/<encoded>``  — LEGACY only: a pre-#180 non-sandboxed
     session kept its transcript on the host (cwd ``BASE_WORKDIR/<sid>``). After
     #180 there are none; kept as a defensive fallback. Claude Code derives
     ``<encoded>`` from the cwd by replacing every non-alphanumeric char with ``-``.

``archive_session`` captures whichever exist into one bundle, then removes the live
copies. It is best-effort and FAIL-SAFE: if writing the bundle raises, the live
copies are left untouched (we never lose data to a half-write).
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

# Where archived bundles live, relative to BASE_WORKDIR. Leading underscore keeps
# it out of the way of the sid-named live session dirs (sids are hex, never this).
ARCHIVE_DIRNAME = "_archive"


def transcript_dir(workdir: str | Path, claude_home: Path | None = None) -> Path:
    """The ``~/.claude/projects/<encoded>`` directory holding a session's
    transcript ``*.jsonl`` for the given working directory.

    Claude Code names the project dir after the cwd, replacing every
    non-alphanumeric character with ``-`` (so ``/root/claude/claude-tg-bot/
    workdirs/cf8c89`` → ``-root-claude-claude-tg-bot-workdirs-cf8c89``). Verified
    against the live deployment's project dirs.
    """
    home = claude_home or (Path.home() / ".claude")
    encoded = re.sub(r"[^A-Za-z0-9]", "-", str(Path(workdir)))
    return home / "projects" / encoded


def _dir_size(path: Path) -> int:
    """Total bytes under ``path`` (best effort; 0 on any error)."""
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
    """Move a deleted session's workdir + sandbox state + transcript into a single
    ``.tar.gz`` under ``BASE_WORKDIR/_archive/<owner_id>/`` and remove the live
    copies. Returns the bundle path, or ``None`` if there was nothing to archive.

    Scope is intentionally conservative — exactly the two live dirs the old delete
    path removed (``<sid>`` and ``<sid>.sbxstate``) PLUS the transcript dir, and
    the transcript is only touched when its name ends with the sid (so the shared
    ``~/.claude/projects/-root-claude-claude-tg-bot`` repo transcript can never be
    swept up by accident). Fail-safe: if writing the bundle raises, the partial
    bundle is removed and the live copies are LEFT IN PLACE (no data loss).
    """
    base = Path(base_workdir)
    # #181: the whole per-session dir <sid>/ (holding work/ + state/) is one bundle.
    # was: workdir = base/sid, sbx = base/f"{sid}.sbxstate" (sibling layout, pre-#181).
    session_dir = base / sid
    tdir = transcript_dir(session_dir, claude_home)

    # (arcname inside the bundle, live path on disk) for each piece that exists.
    sources: list[tuple[str, Path]] = []
    if session_dir.is_dir():
        sources.append(("session", session_dir))
    # Legacy/defensive: a pre-#180 host transcript for a NON-sandboxed session (cwd
    # == base/sid). After #180 every session is jailed so its transcript lives in
    # <sid>/state (inside the bundle above) and this rarely matches. Guard: only this
    # session's dir (name ends with the sid), never the shared repo-root projects dir.
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

    # Sidecar meta for a future archive browser (#178) — list without un-taring.
    with contextlib.suppress(Exception):
        (arch_root / f"{sid}-{stamp}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # Bundle is safely on disk — now free the live space.
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
    """Delete archived session bundles older than ``max_age_days`` (#178 retention).

    Sweeps ``BASE_WORKDIR/_archive`` for ``*.tar.gz`` bundles whose mtime is older
    than the cutoff, removing each bundle and its ``*.json`` sidecar. Returns
    ``(bundles_removed, bytes_freed)``. A non-positive ``max_age_days`` means "keep
    forever" → a no-op. Conservative + fail-soft: only ``*.tar.gz`` files under the
    ``_archive`` tree are touched, age is by file mtime, and any per-file error is
    swallowed so one bad file can't stall the sweep (nothing else is removed).
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
        # Drop the matching sidecar meta (``<sid>-<stamp>.json``), best effort.
        sidecar = bundle.parent / (bundle.name[: -len(".tar.gz")] + ".json")
        with contextlib.suppress(OSError):
            sidecar.unlink()
    if removed:
        log.info(
            "archive purge: removed %d bundle(s), freed %d bytes (retention %s d)",
            removed, freed, max_age_days,
        )
    return (removed, freed)
