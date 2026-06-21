"""Proactive OAuth token refresh (#191) — keep ``~/.claude/.credentials.json`` fresh.

The subscription OAuth ACCESS token has a hard ~8 h life (``expiresAt``). Nothing in
the running bot rotates it: the idle reaper kills the ``claude`` subprocess within
minutes, and a freshly-spawned one just re-reads the SAME on-disk token — so after an
idle gap longer than the token life (e.g. overnight) every turn 401s until a manual
re-login. This module owns the OAuth ``refresh_token -> access_token`` exchange (the
piece the #119 broker will eventually subsume) and rewrites the creds file ATOMICALLY
before the token expires, so a turn after any idle gap gets a valid bearer with no
re-login.

P0 (subscription billing): this is pure OAuth — the refresh grant sends only the
``refresh_token`` + the PUBLIC Claude Code ``client_id`` (a PKCE public client, no
secret) and stores the returned OAuth tokens. It NEVER writes an ``ANTHROPIC_API_KEY``
/ ``ANTHROPIC_AUTH_TOKEN``, so billing stays on the subscription.

Fail-soft: every error leaves the existing creds UNTOUCHED — the bot then behaves
exactly as before (the engine self-heal on a 401, or a manual re-login). Token
material is never logged.

The endpoint + client_id below are the values the bundled ``claude`` CLI itself uses
(``platform.claude.com`` + the public Claude Code client id); if Anthropic ever
rotates them, refreshes start returning "fail" and the bot falls back to today's
behaviour — nothing breaks.
"""

import asyncio
import contextlib
import json
import logging
import os
import time
import urllib.error
import urllib.request

logger = logging.getLogger("token_refresh")

# OAuth token endpoint + public client id, as used by the `claude` CLI itself.
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_DEFAULT_CREDS = "~/.claude/.credentials.json"


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "") or default))
    except (TypeError, ValueError):
        return default


# Tunables (.env, optional). Token lives ~8 h; renewing when <1 h remains, swept every
# 30 min, renews it well before any idle gap can outlast it (and one missed sweep still
# has hours of margin).
DEFAULT_SKEW_SECONDS = _env_int("OAUTH_REFRESH_SKEW_SEC", 3600)
DEFAULT_INTERVAL_SECONDS = _env_int("OAUTH_REFRESH_INTERVAL_SEC", 1800)


def _read_creds(path: str):
    """Load the WHOLE credentials JSON (so we can rewrite it intact). Returns the dict
    or None on any read/parse failure."""
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _seconds_left(oauth) -> float | None:
    """Seconds until the access token expires, from ``expiresAt`` (epoch MILLIS)."""
    exp = oauth.get("expiresAt") if isinstance(oauth, dict) else None
    try:
        return float(exp) / 1000.0 - time.time()
    except (TypeError, ValueError):
        return None


def _refresh_sync(refresh_token: str, timeout: float):
    """Blocking POST of the refresh-token grant. Returns the parsed token response
    (``access_token`` / ``refresh_token`` / ``expires_in``) or None on any failure.
    Never raises; never logs the tokens."""
    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": _CLIENT_ID,
    }).encode("utf-8")
    req = urllib.request.Request(
        _TOKEN_URL, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "claude-tg-bot",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return None
            data = json.load(r)
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _write_creds_atomic(path: str, data: dict) -> bool:
    """Write the creds JSON atomically: a temp file in the SAME dir (0600) + an atomic
    ``os.replace``, so a concurrent reader (a spawning ``claude``) never sees a partial
    or world-readable file. Returns True on success; leaves no temp on failure."""
    full = os.path.expanduser(path)
    tmp = f"{full}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, full)
        return True
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        return False


def refresh_now_sync(path: str = _DEFAULT_CREDS, timeout: float = 20.0) -> str:
    """UNCONDITIONALLY refresh the access token from the stored refresh token and
    rewrite the creds file. Returns a short status string for logging. Fail-soft: on
    any error the existing file is left untouched. Never logs token material."""
    creds = _read_creds(path)
    if creds is None:
        return "skip: creds unreadable"
    oauth = creds.get("claudeAiOauth")
    if not isinstance(oauth, dict) or not oauth.get("refreshToken"):
        return "skip: no refresh token"
    resp = _refresh_sync(oauth["refreshToken"], timeout)
    if not resp or not resp.get("access_token"):
        return "fail: refresh request rejected"
    # Merge the new tokens INTO the existing blob, preserving scopes / subscriptionType
    # / rateLimitTier the response doesn't echo back.
    oauth["accessToken"] = resp["access_token"]
    if resp.get("refresh_token"):
        oauth["refreshToken"] = resp["refresh_token"]   # refresh tokens may rotate
    try:
        ttl = int(resp.get("expires_in") or 0)
    except (TypeError, ValueError):
        ttl = 0
    if ttl > 0:
        oauth["expiresAt"] = int((time.time() + ttl) * 1000)
    creds["claudeAiOauth"] = oauth
    if not _write_creds_atomic(path, creds):
        return "fail: write error"
    return f"ok: refreshed (ttl~{ttl // 3600}h)" if ttl else "ok: refreshed"


async def maybe_refresh(path: str = _DEFAULT_CREDS, skew: float = DEFAULT_SKEW_SECONDS,
                        timeout: float = 20.0, force: bool = False) -> str:
    """Refresh only if the access token expires within ``skew`` seconds (or ``force``).
    Runs the blocking HTTP + file I/O in a thread. Returns a status string."""
    creds = _read_creds(path)
    if creds is None:
        return "skip: creds unreadable"
    left = _seconds_left(creds.get("claudeAiOauth") or {})
    if not force and left is not None and left > skew:
        return f"skip: {int(left)}s left"
    return await asyncio.to_thread(refresh_now_sync, path, timeout)


async def refresh_loop(interval: float = DEFAULT_INTERVAL_SECONDS,
                       skew: float = DEFAULT_SKEW_SECONDS,
                       path: str = _DEFAULT_CREDS) -> None:
    """Background loop (#191): every ``interval`` seconds, refresh the OAuth token if
    it is within ``skew`` of expiry. Started next to the usage poller / reaper and
    cancelled on shutdown. Self-contained + fail-soft — a bad sweep only logs."""
    logger.info("token refresh: sweep every %ds, renew when <%ds left", int(interval), int(skew))
    while True:
        try:
            status = await maybe_refresh(path=path, skew=skew)
            if not status.startswith("skip"):
                logger.info("token refresh: %s", status)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.warning("token refresh sweep failed", exc_info=True)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
