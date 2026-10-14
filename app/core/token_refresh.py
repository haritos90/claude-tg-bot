"""Proactively refreshes the OAuth token in the credentials file.

- Access token lives about 8 hours
- Idle-reaped `claude` respawns would reread a stale token
- Rewrites the creds file atomically before expiry
- Sends only `refresh_token` and public `client_id`; never API keys
- Fail-soft: errors leave creds untouched; tokens never logged
"""

import asyncio
import concurrent.futures
import contextlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable

logger = logging.getLogger("token_refresh")

# OAuth endpoint and public client id used by `claude`.
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_DEFAULT_CREDS = "~/.claude/.credentials.json"


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "") or default))
    except (TypeError, ValueError):
        return default


# Token lives ~8 h; renew under 1 h left.
# - Swept every 30 min; one miss is safe
DEFAULT_SKEW_SECONDS = _env_int("OAUTH_REFRESH_SKEW_SEC", 3600)
DEFAULT_INTERVAL_SECONDS = _env_int("OAUTH_REFRESH_INTERVAL_SEC", 1800)

# Bound every sweep so the loop cannot park.
# - urllib socket timeout does not cover DNS resolution
# - Abandoned blocking calls go to a dedicated 1-thread pool
# - Heartbeat every Nth sweep makes a stopped loop visible
DEFAULT_SWEEP_DEADLINE_SECONDS = _env_int("OAUTH_REFRESH_SWEEP_DEADLINE_SEC", 120)
DEFAULT_HEARTBEAT_EVERY = _env_int("OAUTH_REFRESH_HEARTBEAT_EVERY", 6)  # about every 3 hours

# Warn the owner when the login nears its deadline.
# - Refresh token expires roughly monthly (`refreshTokenExpiresAt`)
# - Refresher renews only the access token
# - Expiry then needs a manual `claude` re-login
LOGIN_EXPIRY_WARN_DAYS = _env_int("LOGIN_EXPIRY_WARN_DAYS", 3)

# Push an owner alert when refresh failure looks persistent.
# - Early-dead tokens (revoked, rotated) never trip the nominal-deadline warning
# - Turns then fail with a generic server-side error
# - Repeats every N sweeps while broken
# - Sends an all-clear on recovery
ALERT_AFTER_FAILS = _env_int("OAUTH_ALERT_AFTER_FAILS", 2)          # same threshold as log escalation
ALERT_REPEAT_SWEEPS = _env_int("OAUTH_ALERT_REPEAT_SWEEPS", 12)     # about every 6 hours


def _read_creds(path: str):
    """Load the whole credentials JSON, or None on failure."""
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _seconds_left(oauth) -> float | None:
    """Seconds until the access token expires, from epoch-millis `expiresAt`."""
    exp = oauth.get("expiresAt") if isinstance(oauth, dict) else None
    try:
        return float(exp) / 1000.0 - time.time()
    except (TypeError, ValueError):
        return None


def login_seconds_left(path: str = _DEFAULT_CREDS) -> float | None:
    """Seconds until the login itself expires, or None.

    - Read from epoch-millis `refreshTokenExpiresAt`
    - After it, a manual `claude` re-login is required
    """
    creds = _read_creds(path)
    oauth = creds.get("claudeAiOauth") if isinstance(creds, dict) else None
    exp = oauth.get("refreshTokenExpiresAt") if isinstance(oauth, dict) else None
    try:
        return float(exp) / 1000.0 - time.time()
    except (TypeError, ValueError):
        return None


def login_warn_days(seconds_left: float | None,
                    warn_days: int = LOGIN_EXPIRY_WARN_DAYS) -> int | None:
    """Whole days for a login-expiry warning, else None.

    - Floors, with a minimum of 1 (covers expired)
    - Pure; caller owns throttle and i18n
    """
    if seconds_left is None or seconds_left > warn_days * 86400:
        return None
    return max(1, int(seconds_left // 86400))


def _refresh_sync(refresh_token: str, timeout: float):
    """Blocking POST of the refresh-token grant; None on failure.

    - Never raises; never logs tokens
    """
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
    """Atomically write creds JSON via a same-directory temp file.

    - Temp file is 0600, swapped in with `os.replace`
    - Readers never see a partial file
    - Returns True on success; no temp left on failure
    """
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
    """Unconditionally refresh the access token and rewrite creds.

    - Returns a short status string for logging
    - Fail-soft: errors leave the file untouched
    """
    creds = _read_creds(path)
    if creds is None:
        return "skip: creds unreadable"
    oauth = creds.get("claudeAiOauth")
    if not isinstance(oauth, dict) or not oauth.get("refreshToken"):
        return "skip: no refresh token"
    resp = _refresh_sync(oauth["refreshToken"], timeout)
    if not resp or not resp.get("access_token"):
        return "fail: refresh request rejected"
    # Merge new tokens into the existing blob.
    # - Preserves scopes, subscriptionType, rateLimitTier the response omits
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
                        timeout: float = 20.0, force: bool = False,
                        executor: "concurrent.futures.Executor | None" = None) -> str:
    """Refresh only if the token expires within `skew` seconds.

    - `force` bypasses the check; returns a status string
    - Blocking work runs in a thread
    - Optional `executor` keeps wedged calls off shared pool
    """
    creds = _read_creds(path)
    if creds is None:
        return "skip: creds unreadable"
    left = _seconds_left(creds.get("claudeAiOauth") or {})
    if not force and left is not None and left > skew:
        return f"skip: {int(left)}s left"
    if executor is not None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, refresh_now_sync, path, timeout)
    return await asyncio.to_thread(refresh_now_sync, path, timeout)


async def refresh_loop(interval: float = DEFAULT_INTERVAL_SECONDS,
                       skew: float = DEFAULT_SKEW_SECONDS,
                       path: str = _DEFAULT_CREDS,
                       sweep_deadline: float = DEFAULT_SWEEP_DEADLINE_SECONDS,
                       heartbeat_every: int = DEFAULT_HEARTBEAT_EVERY,
                       on_alert: "Callable[[str, int], Awaitable[None]] | None" = None) -> None:
    """Background loop refreshing the OAuth token before expiry.

    - Runs every `interval` seconds; cancelled on shutdown
    - Each sweep is bounded by `sweep_deadline`
    - Heartbeat every `heartbeat_every` sweeps exposes a stopped loop
    - Consecutive failures escalate to WARNING
    """
    logger.info("token refresh: sweep every %ds, renew when <%ds left (deadline %ds)",
                int(interval), int(skew), int(sweep_deadline))
    # Dedicated 1-thread pool for the blocking refresh.
    # - A timed-out sweep strands at most one thread
    # - Pool is replaced on every timeout
    # - Otherwise a permanent wedge would block refreshes forever
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="oauth-refresh")
    fails = 0          # consecutive failed sweeps
    sweeps = 0         # liveness heartbeat counter
    status = "startup"
    alerted = False    # owner alert outstanding; send all-clear
    try:
        while True:
            try:
                status = await asyncio.wait_for(
                    maybe_refresh(path=path, skew=skew, executor=executor),
                    timeout=sweep_deadline)
                # Only the "skip: Ns left" case is healthy.
                # - Healthy skip resets the failure streak
                # - Unreadable creds or no refresh token mean broken refresher
                # - Treat those as failures and escalate
                healthy_skip = status.startswith("skip") and status.endswith("left")
                if status.startswith("fail") or (status.startswith("skip") and not healthy_skip):
                    fails += 1
                    # Repeated failures log loudly, not as easy-to-miss INFO.
                    # - Cause: revoked or rotated refresh token, or unreadable creds
                    level = logging.WARNING if fails >= 2 else logging.INFO
                    logger.log(level, "token refresh: %s (%d consecutive%s)", status, fails,
                               "; manual re-login likely needed" if fails >= 2 else "")
                else:
                    if status.startswith("ok"):
                        logger.info("token refresh: %s", status)   # an actual refresh
                    fails = 0
            except asyncio.TimeoutError:
                fails += 1
                status = "fail: sweep timed out"
                # A single timeout is INFO; only a repeat warns.
                # - A repeat suggests a persistent DNS or socket wedge
                level = logging.WARNING if fails >= 2 else logging.INFO
                logger.log(level, "token refresh: sweep exceeded %ds (blocked DNS/socket?) — "
                           "abandoned, will retry (%d consecutive)",
                           int(sweep_deadline), fails)
                # Replace the pool after a timeout.
                # - Abandoned worker holds the pool's only slot
                # - Otherwise later sweeps queue behind it, then burst-rotate tokens
                # - `cancel_futures` drops the backlog
                # - Leaks at most one thread per permanent wedge
                executor.shutdown(wait=False, cancel_futures=True)
                executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="oauth-refresh")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                # Record unexpected-exception sweeps in `status` and count as failed.
                # - Keeps the heartbeat's last status accurate
                # - Persistent exceptions then feed consecutive-failure escalation
                fails += 1
                status = f"fail: {type(exc).__name__}"
                logger.warning("token refresh sweep failed", exc_info=True)
            # Push escalation to the owner as well as journald.
            # - A dead login makes every turn fail generically
            # - The alert is the only message naming the cause
            # - Terminal skips alert on first occurrence
            if on_alert is not None:
                terminal = status.startswith("skip")     # only non-healthy skips reach here
                threshold = 1 if terminal else ALERT_AFTER_FAILS
                with contextlib.suppress(Exception):
                    if fails >= threshold:
                        since = fails - threshold
                        if since == 0 or (ALERT_REPEAT_SWEEPS > 0
                                          and since % ALERT_REPEAT_SWEEPS == 0):
                            await on_alert(status, fails)
                            alerted = True
                    elif fails == 0 and alerted:
                        await on_alert("ok: recovered", 0)
                        alerted = False
            sweeps += 1
            if heartbeat_every > 0 and sweeps % heartbeat_every == 0:
                # These lines sit outside the per-sweep try/except.
                # - Guard heartbeat log so errors cannot kill the loop
                with contextlib.suppress(Exception):
                    logger.info("token refresh: alive — %d sweeps done, last status: %s",
                                sweeps, status)
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
