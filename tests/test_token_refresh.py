"""Tests for the proactive OAuth token refresher (#191).

The network call (`_refresh_sync`) is monkeypatched, so these never touch the real
endpoint. They verify the merge/atomic-write, the skew gate, and the fail-soft
contract (a bad refresh leaves the creds file untouched).
"""

import asyncio
import json
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
