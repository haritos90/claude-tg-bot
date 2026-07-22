"""Tests for the proactive OAuth token refresher (#191).

The network call (`_refresh_sync`) is monkeypatched, so these never touch the real
endpoint. They verify the merge/atomic-write, the skew gate, and the fail-soft
contract (a bad refresh leaves the creds file untouched).
"""

import asyncio
import concurrent.futures
import contextlib
import json
import logging
import os
import tempfile
import time

from app.core import token_refresh


def _write(path, oauth):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"claudeAiOauth": oauth, "other": "kept"}, fh)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_refresh_merges_and_preserves_and_is_atomic(monkeypatch):
    path = tempfile.mktemp(suffix=".json")
    _write(path, {
        "accessToken": "OLD", "refreshToken": "R1", "expiresAt": 1000,
        "scopes": ["a", "b"], "subscriptionType": "max",
    })
    monkeypatch.setattr(token_refresh, "_refresh_sync",
                        lambda rt, to: {"access_token": "NEW", "refresh_token": "R2",
                                        "expires_in": 28800})
    status = token_refresh.refresh_now_sync(path)
    assert status.startswith("ok")
    data = _read(path)
    o = data["claudeAiOauth"]
    assert o["accessToken"] == "NEW" and o["refreshToken"] == "R2"
    # expiresAt moved ~8h into the future (ms).
    assert o["expiresAt"] > (time.time() + 28000) * 1000
    # Untouched fields preserved.
    assert o["scopes"] == ["a", "b"] and o["subscriptionType"] == "max"
    assert data["other"] == "kept"
    # No temp file left behind.
    assert not os.path.exists(path + ".tmp")
    os.remove(path)


def test_refresh_failsoft_leaves_file_untouched(monkeypatch):
    path = tempfile.mktemp(suffix=".json")
    _write(path, {"accessToken": "OLD", "refreshToken": "R1", "expiresAt": 1000})
    monkeypatch.setattr(token_refresh, "_refresh_sync", lambda rt, to: None)
    status = token_refresh.refresh_now_sync(path)
    assert status.startswith("fail")
    assert _read(path)["claudeAiOauth"]["accessToken"] == "OLD"  # unchanged
    os.remove(path)


def test_no_refresh_token_skips(monkeypatch):
    path = tempfile.mktemp(suffix=".json")
    _write(path, {"accessToken": "OLD", "expiresAt": 1000})  # no refreshToken
    called = {"n": 0}
    monkeypatch.setattr(token_refresh, "_refresh_sync",
                        lambda rt, to: called.__setitem__("n", called["n"] + 1))
    assert token_refresh.refresh_now_sync(path).startswith("skip")
    assert called["n"] == 0
    os.remove(path)


def test_maybe_refresh_skew_gate(monkeypatch):
    path = tempfile.mktemp(suffix=".json")
    # Token with 2h left, skew 1h → should SKIP (no network call).
    _write(path, {"accessToken": "OLD", "refreshToken": "R1",
                  "expiresAt": int((time.time() + 7200) * 1000)})
    monkeypatch.setattr(token_refresh, "_refresh_sync",
                        lambda rt, to: {"access_token": "NEW", "expires_in": 28800})
    out = asyncio.run(token_refresh.maybe_refresh(path=path, skew=3600))
    assert out.startswith("skip") and _read(path)["claudeAiOauth"]["accessToken"] == "OLD"
    # force=True refreshes regardless.
    out = asyncio.run(token_refresh.maybe_refresh(path=path, skew=3600, force=True))
    assert out.startswith("ok") and _read(path)["claudeAiOauth"]["accessToken"] == "NEW"
    os.remove(path)


def test_missing_file_failsoft():
    assert token_refresh.refresh_now_sync(tempfile.mktemp(suffix=".json")).startswith("skip")


def test_maybe_refresh_via_given_executor(monkeypatch):
    """#378: the blocking refresh runs on a caller-supplied executor (refresh_loop uses a
    dedicated 1-thread pool so a wedged sweep can't starve the shared executor)."""
    path = tempfile.mktemp(suffix=".json")
    _write(path, {"accessToken": "OLD", "refreshToken": "R1", "expiresAt": 1000})
    monkeypatch.setattr(token_refresh, "_refresh_sync",
                        lambda rt, to: {"access_token": "NEW", "expires_in": 28800})
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="t")
    try:
        out = asyncio.run(token_refresh.maybe_refresh(
            path=path, skew=3600, force=True, executor=ex))
    finally:
        ex.shutdown(wait=False)
    assert out.startswith("ok")
    assert _read(path)["claudeAiOauth"]["accessToken"] == "NEW"
    os.remove(path)


async def _run_loop_briefly(**kwargs):
    """Spin refresh_loop for a handful of fast sweeps, then cancel it cleanly."""
    task = asyncio.create_task(token_refresh.refresh_loop(**kwargs))
    await asyncio.sleep(0.1)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def test_refresh_loop_bounds_a_wedged_sweep(monkeypatch, caplog):
    """#378: a sweep that blocks past the deadline is abandoned and the loop keeps ticking
    and logs it — the exact failure mode that once silenced the loop for hours."""
    async def hang(**kw):
        await asyncio.sleep(30)          # never returns within the deadline below
        return "ok: refreshed"
    monkeypatch.setattr(token_refresh, "maybe_refresh", hang)
    # #380: the FIRST timeout logs at INFO now (only a repeat escalates), so capture INFO
    # to catch it regardless of how many sweeps the brief window happens to fit.
    with caplog.at_level(logging.INFO, logger="token_refresh"):
        asyncio.run(_run_loop_briefly(interval=0.005, path="/nope",
                                      sweep_deadline=0.02, heartbeat_every=0))
    assert any("sweep exceeded" in r.getMessage() for r in caplog.records)


def test_refresh_loop_escalates_and_heartbeats(monkeypatch, caplog):
    """#378: consecutive failures escalate to WARNING (with a re-login hint) and a liveness
    heartbeat is emitted — so a stuck loop is distinguishable from a healthy idle one."""
    async def fail(**kw):
        return "fail: refresh request rejected"
    monkeypatch.setattr(token_refresh, "maybe_refresh", fail)
    with caplog.at_level(logging.INFO, logger="token_refresh"):
        asyncio.run(_run_loop_briefly(interval=0.005, path="/nope", heartbeat_every=3))
    msgs = [r.getMessage() for r in caplog.records]
    assert any("consecutive" in m and "re-login" in m for m in msgs)   # escalated
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert any("alive" in m for m in msgs)                             # heartbeat


def test_login_seconds_left_reads_refresh_expiry():
    """#379: login expiry comes from refreshTokenExpiresAt (the ~monthly deadline), NOT
    the 8h access-token expiresAt."""
    path = tempfile.mktemp(suffix=".json")
    exp = int((time.time() + 2 * 86400) * 1000)          # 2 days out
    _write(path, {"accessToken": "A", "refreshToken": "R", "expiresAt": 1000,
                  "refreshTokenExpiresAt": exp})
    left = token_refresh.login_seconds_left(path)
    assert left is not None and 1.9 * 86400 < left < 2.1 * 86400
    os.remove(path)


def test_login_seconds_left_absent_field_is_none():
    path = tempfile.mktemp(suffix=".json")
    _write(path, {"accessToken": "A", "refreshToken": "R", "expiresAt": 1000})  # no refresh expiry
    assert token_refresh.login_seconds_left(path) is None
    os.remove(path)


def test_login_warn_days_threshold_and_floor():
    """#379: only within the window; floors so it never overstates the days left."""
    day = 86400
    assert token_refresh.login_warn_days(5 * day, warn_days=3) is None    # outside window
    assert token_refresh.login_warn_days(2.7 * day, warn_days=3) == 2     # floors, not 3
    assert token_refresh.login_warn_days(0.3 * day, warn_days=3) == 1     # floor of 1
    assert token_refresh.login_warn_days(-5 * day, warn_days=3) == 1      # already expired
    assert token_refresh.login_warn_days(None) is None


def test_login_warn_days_exact_boundary():
    """#380: pin the strict `>` boundary so an off-by-one flip to `>=` is caught — exactly
    warn_days out is still INSIDE the window, a hair past it is outside."""
    day = 86400
    assert token_refresh.login_warn_days(3 * day, warn_days=3) == 3        # exactly at edge → inside
    assert token_refresh.login_warn_days(3 * day + 1, warn_days=3) is None  # just past → outside


def test_refresh_loop_escalation_resets_on_success(monkeypatch, caplog):
    """#380: a successful sweep resets the consecutive-failure counter, so escalation is
    CONSECUTIVE-only — after fail,fail (→ one WARNING) an ok resets and the next fail is
    INFO again, never a second WARNING."""
    calls = {"n": 0}
    # fail, fail, ok, fail, then ok forever — the ok tail adds no warnings, so the assertion
    # does not depend on exactly how many sweeps the brief window fits (only that it runs 4+).
    script = ["fail: rejected", "fail: rejected", "ok: refreshed", "fail: rejected"]

    async def scripted(**kw):
        i = calls["n"]
        calls["n"] += 1
        return script[i] if i < len(script) else "ok: refreshed"

    monkeypatch.setattr(token_refresh, "maybe_refresh", scripted)
    with caplog.at_level(logging.INFO, logger="token_refresh"):
        asyncio.run(_run_loop_briefly(interval=0.002, path="/nope",
                                      sweep_deadline=1.0, heartbeat_every=0))
    assert calls["n"] >= 4                          # the whole script actually ran
    warns = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    # Only the 2nd of the first failure pair escalates; the ok resets fails to 0, so the 4th
    # (a lone failure, fails == 1) stays INFO — exactly one WARNING total.
    assert len(warns) == 1 and "2 consecutive" in warns[0]


def test_refresh_loop_timeout_escalates_on_repeat(monkeypatch, caplog):
    """#380/#385/#386: the SWEEP-TIMEOUT path escalates to WARNING on the 2nd consecutive timeout
    (the first stays INFO), independently of the fail-status path; AND #385 recreates the single-
    thread executor after each timeout so a permanent DNS/socket wedge self-heals — the wedged
    worker is abandoned and the next sweep gets a live pool."""
    async def hang(**kw):
        await asyncio.sleep(30)                 # never returns within the tiny deadline below
        return "ok: refreshed"
    monkeypatch.setattr(token_refresh, "maybe_refresh", hang)
    # #385/#386: record every ThreadPoolExecutor construction — startup makes one and each sweep
    # timeout must REPLACE it. Delete the recreate in refresh_loop and made["n"] stays 1 → this fails.
    made = {"n": 0}
    real_pool = token_refresh.concurrent.futures.ThreadPoolExecutor

    def _recording_pool(*a, **k):
        made["n"] += 1
        return real_pool(*a, **k)

    monkeypatch.setattr(token_refresh.concurrent.futures, "ThreadPoolExecutor", _recording_pool)
    with caplog.at_level(logging.INFO, logger="token_refresh"):
        asyncio.run(_run_loop_briefly(interval=0.002, path="/nope",
                                      sweep_deadline=0.01, heartbeat_every=0))
    timeouts = [(r.levelno, r.getMessage()) for r in caplog.records
                if "sweep exceeded" in r.getMessage()]
    assert any(lv == logging.INFO and "1 consecutive" in m for lv, m in timeouts)     # 1st: INFO
    warns = [m for lv, m in timeouts if lv == logging.WARNING]
    assert warns and "2 consecutive" in warns[0]                                      # 2nd: WARNING
    assert made["n"] >= 2                       # #385: startup pool + at least one per-timeout recreate


def test_refresh_loop_broken_skip_counts_as_failure(monkeypatch, caplog):
    """#385: a 'skip: creds unreadable' / 'skip: no refresh token' means the refresher is broken,
    not idle — it escalates like a failure (does NOT reset the streak), unlike 'skip: Ns left'."""
    async def broken(**kw):
        return "skip: creds unreadable"
    monkeypatch.setattr(token_refresh, "maybe_refresh", broken)
    with caplog.at_level(logging.INFO, logger="token_refresh"):
        asyncio.run(_run_loop_briefly(interval=0.002, path="/nope",
                                      sweep_deadline=1.0, heartbeat_every=0))
    warns = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("creds unreadable" in m and "consecutive" in m for m in warns)
