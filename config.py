"""Application configuration loaded from a .env file in the current working directory.

Exposes a typed Settings dataclass and load_settings(), which validates required
environment variables and warns (without raising) when ANTHROPIC_API_KEY is set,
since that would force paid API billing instead of the Pro/Max subscription.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Default model id used when DEFAULT_MODEL is not provided in the environment.
DEFAULT_MODEL = "claude-opus-4-8"
# Default base directory for per-thread working directories.
DEFAULT_BASE_WORKDIR = "./workdirs"
# Default SQLite database path for persisted per-thread state and usage.
DEFAULT_DB_PATH = "./bot.db"
# Default path to the JSON allowlist file.
DEFAULT_ALLOWLIST_PATH = "./allowlist.json"


@dataclass
class Settings:
    """Runtime configuration for the Telegram bot."""

    bot_token: str
    owner_id: int
    default_model: str
    base_workdir: Path
    db_path: Path
    allowlist_path: Path
    # Per-code-session sandbox (#104). ON by default (#136) — when on, each code
    # session's `claude` runs in a bubblewrap jail: unprivileged uid, confined to
    # its workdir, credential injected read-only. See deploy/sandbox-claude.sh.
    # was `= False` (opt-in) — flipped to default-on for #136 so a code session
    # can only write inside its own workdir (the agent was creating files outside
    # it, e.g. an imagined /Users/<name> home, when running un-jailed as root).
    sandbox_code: bool = True
    sandbox_uid: int = 65534          # the unprivileged uid/gid the jail drops to
    sandbox_allow_exec: bool = True   # True = perm "7" (exec ok); False = "6" (noexec workdir)
    # Extra prompt keyword triggers to neutralize, ON TOP of the built-in defaults
    # (engine.DEFAULT_KEYWORD_TRIGGERS = ultrathink, ultracode). Loaded from
    # BLOCKED_PROMPT_KEYWORDS (comma/space-separated). Each word is made inert in
    # user prompts so it can't trigger a hidden CLI behaviour — see the README and
    # engine.defuse_triggers. Empty by default (the defaults still apply).
    extra_blocked_keywords: list[str] = field(default_factory=list)


def load_settings() -> Settings:
    """Read configuration from a .env file in the CWD and return Settings.

    Required environment variables:
        TELEGRAM_BOT_TOKEN -- Telegram Bot API token.
        OWNER_ID           -- integer Telegram user id allowed to use the bot.

    Optional environment variables:
        DEFAULT_MODEL  -- model id (default "claude-opus-4-8").
        BASE_WORKDIR   -- base directory for per-thread cwds (default "./workdirs").
        DB_PATH        -- SQLite database path (default "./bot.db").
        ALLOWLIST_PATH -- JSON allowlist file path (default "./allowlist.json").

    Side effects:
        - Creates base_workdir if it does not exist.
        - Prints a WARNING to stderr if ANTHROPIC_API_KEY is set (does not raise).

    Raises:
        ValueError: if a required variable is missing or OWNER_ID is not an int.
    """
    # Load variables from a .env file in the current working directory, if present.
    # Existing process environment values take precedence over the file.
    load_dotenv(override=False)

    # Warn (do not raise) if an API key is present: it would force paid API billing
    # instead of using the logged-in subscription credentials of the claude CLI.
    if os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "WARNING: ANTHROPIC_API_KEY is set. This will force PAID API billing "
            "instead of the Claude Pro/Max subscription. Unset it (and "
            "ANTHROPIC_AUTH_TOKEN) so the bot uses your subscription.",
            file=sys.stderr,
        )

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ValueError(
            "Missing required environment variable TELEGRAM_BOT_TOKEN. "
            "Set it in your .env file or environment."
        )

    owner_id_raw = os.environ.get("OWNER_ID")
    if not owner_id_raw:
        raise ValueError(
            "Missing required environment variable OWNER_ID. "
            "Set it to your numeric Telegram user id in .env or the environment."
        )
    try:
        owner_id = int(owner_id_raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"OWNER_ID must be an integer Telegram user id, got: {owner_id_raw!r}."
        ) from exc

    default_model = os.environ.get("DEFAULT_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    # Resolve to an ABSOLUTE path (#136): the per-session cwd is derived from this
    # and passed to the sandbox launcher (which binds it + derives SBX_STATE from
    # it). A relative base made SBX_STATE relative-to-the-jail-cwd and broke
    # session-state persistence. was: Path(os.environ.get(...) or DEFAULT)
    base_workdir = Path(
        os.environ.get("BASE_WORKDIR", DEFAULT_BASE_WORKDIR).strip() or DEFAULT_BASE_WORKDIR
    ).resolve()
    db_path = Path(
        os.environ.get("DB_PATH", DEFAULT_DB_PATH).strip() or DEFAULT_DB_PATH
    )
    allowlist_path = Path(
        os.environ.get("ALLOWLIST_PATH", DEFAULT_ALLOWLIST_PATH).strip()
        or DEFAULT_ALLOWLIST_PATH
    )

    # Ensure the base working directory exists (parents included).
    base_workdir.mkdir(parents=True, exist_ok=True)

    def _flag(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "yes", "on")

    sandbox_code = _flag("SANDBOX_CODE", True)  # #136: default-on (was False)
    try:
        sandbox_uid = int(os.environ.get("SANDBOX_UID", "65534").strip() or "65534")
    except ValueError:
        sandbox_uid = 65534
    sandbox_allow_exec = _flag("SANDBOX_EXEC", True)

    # Extra keyword triggers to neutralize in prompts (on top of the engine
    # defaults). Comma- or whitespace-separated; blanks dropped.
    raw_keywords = os.environ.get("BLOCKED_PROMPT_KEYWORDS", "") or ""
    extra_blocked_keywords = [w for w in re.split(r"[,\s]+", raw_keywords.strip()) if w]

    return Settings(
        bot_token=bot_token,
        owner_id=owner_id,
        default_model=default_model,
        base_workdir=base_workdir,
        db_path=db_path,
        allowlist_path=allowlist_path,
        sandbox_code=sandbox_code,
        sandbox_uid=sandbox_uid,
        sandbox_allow_exec=sandbox_allow_exec,
        extra_blocked_keywords=extra_blocked_keywords,
    )
