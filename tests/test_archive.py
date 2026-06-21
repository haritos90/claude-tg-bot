"""Unit tests for the session cold-storage archiver (#177).

archive.archive_session is synchronous, so these are plain pytest functions
using the tmp_path fixture — no event loop needed.
"""

import io
import json
import os
import tarfile
import time
from pathlib import Path

from app.storage import archive


def _seed(base: Path, sid: str, home: Path):
    """Create a fake NESTED session footprint (#181): <sid>/work + <sid>/state +
    a legacy host transcript dir (named for cwd == base/sid). Returns the
    transcript dir path."""
    (base / sid / "work").mkdir(parents=True)
    (base / sid / "work" / "hello.txt").write_text("made by code", encoding="utf-8")
    (base / sid / "state").mkdir(parents=True)
    (base / sid / "state" / "keep").write_text("sbx", encoding="utf-8")
    tdir = archive.transcript_dir(base / sid, claude_home=home)
    tdir.mkdir(parents=True)
    (tdir / "session.jsonl").write_text('{"x":1}\n', encoding="utf-8")
    return tdir


def test_transcript_dir_encoding(tmp_path):
    """The project dir is the cwd with every non-alphanumeric char → '-'."""
    home = tmp_path / ".claude"
    got = archive.transcript_dir("/var/lib/claude-tg-bot/workdirs/cf8c89/work", home)
    assert got == home / "projects" / "-var-lib-claude-tg-bot-workdirs-cf8c89-work"


def test_archive_bundles_session_and_transcript_and_removes_live(tmp_path):
    base = tmp_path / "workdirs"
    home = tmp_path / ".claude"
    sid = "cf8c89"
    tdir = _seed(base, sid, home)

    bundle = archive.archive_session(
        base, sid, owner_id=42, key=-5, name="Проект",
        claude_home=home, stamp="20260617-000000",
    )

    # Bundle lands under _archive/<owner>/ and is a real gzip tar.
    assert bundle is not None and bundle.exists()
    assert bundle == base / "_archive" / "42" / "cf8c89-20260617-000000.tar.gz"

    names = set(tarfile.open(bundle).getnames())
    assert "session/work/hello.txt" in names      # #181: the whole <sid>/ is bundled
    assert "session/state/keep" in names
    assert "transcript/session.jsonl" in names    # legacy host-transcript fallback
    assert "meta.json" in names

    # Sidecar meta is readable without un-taring and carries the key fields.
    sidecar = base / "_archive" / "42" / "cf8c89-20260617-000000.json"
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["sid"] == sid and meta["owner_id"] == 42 and meta["key"] == -5
    assert meta["name"] == "Проект"
    assert {p["arcname"] for p in meta["parts"]} == {"session", "transcript"}

    # Live copies are gone (space freed).
    assert not (base / sid).exists()
    assert not tdir.exists()


def test_archive_nothing_to_do_returns_none(tmp_path):
    base = tmp_path / "workdirs"
    base.mkdir()
    assert archive.archive_session(base, "deadbe", owner_id=1) is None


def test_archive_leaves_unrelated_transcripts(tmp_path):
    """The sid-suffix guard must never sweep up a foreign project dir (e.g. the
    shared repo-root transcript)."""
    base = tmp_path / "workdirs"
    home = tmp_path / ".claude"
    sid = "cf8c89"
    _seed(base, sid, home)
    foreign = home / "projects" / "-root-claude-claude-tg-bot"
    foreign.mkdir(parents=True)
    (foreign / "mine.jsonl").write_text("keep me", encoding="utf-8")

    archive.archive_session(base, sid, owner_id=7, claude_home=home, stamp="s")

    assert foreign.exists() and (foreign / "mine.jsonl").exists()


def _seed_bundle(arch_dir: Path, name: str, age_days: float) -> Path:
    """Write a real .tar.gz bundle + its .json sidecar, mtime aged by age_days."""
    arch_dir.mkdir(parents=True, exist_ok=True)
    p = arch_dir / f"{name}.tar.gz"
    with tarfile.open(p, "w:gz") as tf:
        data = b"{}"
        info = tarfile.TarInfo("meta.json")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    (arch_dir / f"{name}.json").write_text("{}", encoding="utf-8")
    t = time.time() - age_days * 86400
    os.utime(p, (t, t))
    return p


def test_purge_expired_removes_old_keeps_new(tmp_path):
    """#178: bundles older than the retention (+ their sidecars) are purged; newer
    ones survive."""
    arch = tmp_path / "_archive" / "42"
    old = _seed_bundle(arch, "old-1", 400)   # ~13 months old
    new = _seed_bundle(arch, "new-1", 5)     # 5 days old

    removed, freed = archive.purge_expired(tmp_path, 180)   # 6-month retention
    assert removed == 1 and freed > 0
    assert not old.exists() and not (arch / "old-1.json").exists()
    assert new.exists() and (arch / "new-1.json").exists()


def test_purge_expired_never_is_noop(tmp_path):
    """#178: retention 0 (or negative) means keep forever — nothing is removed."""
    arch = tmp_path / "_archive" / "7"
    old = _seed_bundle(arch, "ancient", 9999)
    assert archive.purge_expired(tmp_path, 0) == (0, 0)
    assert archive.purge_expired(tmp_path, -5) == (0, 0)
    assert old.exists()


def test_purge_expired_missing_archive_dir_is_safe(tmp_path):
    """No _archive tree yet → a clean (0, 0), never an error."""
    assert archive.purge_expired(tmp_path, 180) == (0, 0)
