"""Application settings loaded from a .env file.

- Typed `Settings` dataclass built by `load_settings()`
- Warns, never raises, if ANTHROPIC_API_KEY is set
- That key would force paid API billing
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Default model: the CLI's own "default" alias.
# - Resolved by the CLI; no model family named in code
# - Pin a family in .env, e.g. DEFAULT_MODEL=opus
DEFAULT_MODEL = "default"
# Default base directory for per-thread working directories.
DEFAULT_BASE_WORKDIR = "./workdirs"
# Default SQLite path for per-thread state and usage.
DEFAULT_DB_PATH = "./bot.db"
# Default path to the JSON allowlist file.
DEFAULT_ALLOWLIST_PATH = "./allowlist.json"


def _mem_total_mb() -> int:
    """Total RAM in MiB from /proc/meminfo.

    - Returns 2048 if unknown
    """
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 2048


@dataclass
class Settings:
    """Runtime configuration for the Telegram bot."""

    bot_token: str
    owner_id: int
    default_model: str
    base_workdir: Path
    db_path: Path
    allowlist_path: Path
    # Per-code-session sandbox, on by default.
    # - Runs `claude` in a bubblewrap jail
    # - Unprivileged uid, confined to its workdir
    # - Un-jailed runs wrote files outside the workdir
    # - See deploy/sandbox-claude.sh
    sandbox_code: bool = True
    sandbox_uid: int = 65534          # unprivileged uid/gid inside the jail
    sandbox_allow_exec: bool = True   # True allows exec; False noexec
    # Per-session unprivileged host uid; off by default.
    # - Jail runs as a distinct non-root uid via setpriv
    # - Workdir is chowned to that uid (0700)
    # - An escape cannot read other sessions' files
    # - Needs unprivileged userns and setpriv
    sandbox_per_session_uid: bool = False
    sandbox_uid_base: int = 700000    # host uid: base plus offset
    sandbox_uid_range: int = 60000
    # Credential broker, off by default.
    # - Jail gets a dummy token and a broker base URL
    # - Host broker injects the real OAuth bearer
    # - Subscription token never enters the jail
    cred_broker: bool = False
    cred_broker_port: int = 8789
    # Egress allowlist, off by default.
    # - Jail egress blocked to loopback by cgroup-scoped iptables
    # - Anthropic via broker; dev hosts via CONNECT proxy
    # - Other destinations are dropped
    # - Recommended together with `cred_broker`
    sandbox_egress: bool = False
    egress_proxy_port: int = 8790
    egress_allow_hosts: str = ""      # extra CONNECT-allowlisted hosts
    # Per-jail DoS limits; 0 or empty = unset.
    # - Applied through the cgroup leaf the launcher joins
    # - seccomp loads a denylist BPF when on (x86_64 only)
    sandbox_mem_mb: int = 0           # memory.max in MB
    sandbox_cpu_percent: int = 0      # cpu.max, percent of one core
    sandbox_pids_max: int = 0         # pids.max
    sandbox_seccomp: bool = False
    sandbox_seccomp_path: str = ""    # bot.main writes the compiled BPF here
    # Global per-user session limit; 0 = unlimited.
    # - Per-user override lives in allowlist.json
    max_sessions_default: int = 500
    # Concurrency and RAM caps; defaults derive from the box.
    # - Each live `claude` client uses ~400-600 MB RSS
    # - Idle reaper frees them; `resume` rebuilds on demand
    max_live_clients: int = 4      # max simultaneously live clients
    idle_ttl_sec: int = 360        # reap clients idle past this
                                   # Six minutes = 5-minute warm cache plus buffer
                                   # - No caching gain past it
    # Detached jailed shell survives the client reap.
    # - ~3 MB versus ~500 MB for the client
    # - Keeps cd/env and any running command
    # - Own longer TTL; 0 = until delete or reset
    shell_ttl_sec: int = 86400     # 24 hours
    # Rotate a quiet session to a fresh context.
    # - Avoids re-ingesting stale history (context drift)
    # - Old transcript and workdir stay on disk
    # - 0 = never; per-user override `idle_reset_min`
    idle_reset_sec: int = 2700     # 45 minutes
    # Run `claude update` daily at this UTC time.
    # - Format HH:MM; "off" = never
    # - Idle clients move at once, busy ones after their turn
    # - Owner can override at runtime via kv `cli_update_at`
    cli_update_at: str = "12:00"
    max_concurrent_turns: int = 4  # cap on simultaneous active turns
    min_free_mb: int = 400         # evict idle clients below this MemAvailable
    # Extra prompt keyword triggers to neutralize.
    # - Added on top of the built-in defaults
    # - Loaded from BLOCKED_PROMPT_KEYWORDS (comma/space-separated)
    # - Each word is made inert in user prompts
    # - Empty by default; defaults still apply
    extra_blocked_keywords: list[str] = field(default_factory=list)
    # Archive retention in days; 0 = keep forever.
    # - Older bundles under `_archive` are auto-purged
    # - Default 6 months
    # - Owner override persists in kv `archive_retention_days`
    archive_retention_days: int = 180
    # Local speech-to-text for voice notes; off by default.
    # - Needs optional ffmpeg and faster-whisper
    # - Transcribed on host; audio never enters the jail
    # - Small model suffices; agent tolerates recognition errors
    voice_transcription: bool = False
    voice_model: str = "base"     # model size or local path
    voice_lang: str = ""          # empty autodetects; else force a language
    voice_max_seconds: int = 300  # max note seconds, 0 unlimited
    voice_model_path: str = ""    # model cache dir; empty = default
    # MAX (max.ru) transport; off unless MAX_BOT_TOKEN set.
    # - Same handlers serve both platforms via a routing session
    # - MAX users have their own id namespace
    # - Owner is an ordinary MAX user; admin stays on Telegram
    max_bot_token: str = ""
    max_api_base: str = "https://platform-api2.max.ru"
    max_ca_bundle: str = ""       # bundled CA, or "system" store


def load_settings() -> Settings:
    """Read .env from the CWD and return Settings.

    - Required: TELEGRAM_BOT_TOKEN and integer OWNER_ID
    - Optional: DEFAULT_MODEL, BASE_WORKDIR, DB_PATH, ALLOWLIST_PATH
    - Creates base_workdir; warns on stderr if API key set
    - Raises ValueError for a missing variable or non-int OWNER_ID
    """
    # Load .env from the CWD if present.
    # - Existing environment values take precedence
    load_dotenv(override=False)

    # Warn, don't raise, if an API key exists.
    # - It would force paid billing over subscription
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
    # Resolve base workdir to an absolute path.
    # - Sandbox launcher derives SBX_STATE from it
    # - A relative path broke session-state persistence
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

    # Ensure the base working directory exists.
    base_workdir.mkdir(parents=True, exist_ok=True)

    def _flag(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "yes", "on")

    sandbox_code = _flag("SANDBOX_CODE", True)
    try:
        sandbox_uid = int(os.environ.get("SANDBOX_UID", "65534").strip() or "65534")
    except ValueError:
        sandbox_uid = 65534
    sandbox_allow_exec = _flag("SANDBOX_EXEC", True)
    # Full isolation is on by default.
    # - Broker, egress block, seccomp, per-session uid default on
    # - Hosts lacking a layer opt out via env flag (=0)
    cred_broker = _flag("CRED_BROKER", True)             # needs the host broker sidecar
    sandbox_egress = _flag("SANDBOX_EGRESS", True)       # needs egress-setup.sh, iptables, cgroup
    sandbox_seccomp = _flag("SANDBOX_SECCOMP", True)     # needs the generated seccomp profile
    sandbox_per_session_uid = _flag("SANDBOX_PER_SESSION_UID", True)  # needs userns; BASE_WORKDIR outside /root
    egress_allow_hosts = (os.environ.get("EGRESS_ALLOW_HOSTS", "") or "").strip()

    # Derive concurrency and RAM caps from the box.
    # - Reserve ~900 MB for OS, bot, buffers
    # - Budget ~550 MB per live client
    def _int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            return default
        try:
            return int(raw.strip())
        except ValueError:
            return default

    _total_mb = _mem_total_mb()
    _cpus = os.cpu_count() or 2
    _default_live = max(2, (_total_mb - 900) // 550)
    _default_turns = max(1, min(_default_live, _cpus * 2))
    max_live_clients = max(1, _int("MAX_LIVE_CLIENTS", _default_live))
    idle_ttl_sec = max(60, _int("IDLE_TTL_SEC", 360))  # 6 min default
                                                       # Warm cache (5 min) plus 1 min buffer
    idle_reset_sec = max(0, _int("IDLE_RESET_SEC", 2700))  # 45-min idle rotates to fresh session
                                                           # 0 = off; per-user override `idle_reset_min`
    # Daily CLI update time, UTC; "off" = never.
    # - Legacy CLI_UPDATE_INTERVAL_HOURS=0 still disables it
    # - Applies only when CLI_UPDATE_AT_UTC is unset
    cli_update_at = (os.environ.get("CLI_UPDATE_AT_UTC") or "").strip()
    if not cli_update_at:
        cli_update_at = ("off" if os.environ.get("CLI_UPDATE_INTERVAL_HOURS", "").strip() == "0"
                         else "12:00")
    shell_ttl_sec = max(0, _int("SHELL_TTL_SEC", 86400))   # detached-shell TTL; 0 = until delete
    max_concurrent_turns = max(1, _int("MAX_CONCURRENT_TURNS", _default_turns))
    min_free_mb = max(0, _int("MIN_FREE_MB", 400))
    cred_broker_port = max(1, _int("CRED_BROKER_PORT", 8789))
    egress_proxy_port = max(1, _int("EGRESS_PROXY_PORT", 8790))
    sandbox_mem_mb = max(0, _int("SANDBOX_MEM_MB", 0))           # 0 = unlimited
    sandbox_cpu_percent = max(0, _int("SANDBOX_CPU_PERCENT", 0))  # 100 = one core
    sandbox_pids_max = max(0, _int("SANDBOX_PIDS_MAX", 0))        # 0 = unlimited
    sandbox_uid_base = max(1000, _int("SANDBOX_UID_BASE", 700000))
    sandbox_uid_range = max(1, _int("SANDBOX_UID_RANGE", 60000))
    max_sessions_default = max(0, _int("MAX_SESSIONS_PER_USER", 500))  # 0 = unlimited
                                                                       # Per-session disk is tiny (~1 MB transcript)
    # Where bot.main writes the seccomp BPF blob.
    # - Under BASE_WORKDIR so bwrap's --seccomp fd can read it
    # - Set only when seccomp is on
    sandbox_seccomp_path = str(base_workdir / ".sbx-seccomp.bpf") if sandbox_seccomp else ""
    # Archive retention in days; 0 = keep forever.
    # - Startup default; owner overrides at runtime (kv `archive_retention_days`)
    archive_retention_days = max(0, _int("ARCHIVE_RETENTION_DAYS", 180))

    # Voice-note transcription; optional deps in requirements/voice.txt.
    # - Language empty = autodetect
    # - Model default "base"; tiny faster, small better
    # - Max seconds default 300; 0 = off
    voice_transcription = _flag("VOICE_TRANSCRIPTION", False)
    voice_model = (os.environ.get("VOICE_MODEL", "") or "").strip() or "base"
    voice_lang = (os.environ.get("VOICE_LANG", "") or "").strip()
    voice_max_seconds = max(0, _int("VOICE_MAX_SECONDS", 300))
    voice_model_path = (os.environ.get("VOICE_MODEL_PATH", "") or "").strip()

    # MAX transport; empty token = off, never logged.
    max_bot_token = (os.environ.get("MAX_BOT_TOKEN", "") or "").strip()
    max_api_base = (os.environ.get("MAX_API_BASE", "") or "").strip() or "https://platform-api2.max.ru"
    max_ca_bundle = (os.environ.get("MAX_CA_BUNDLE", "") or "").strip()

    # Extra keyword triggers to neutralize in prompts.
    # - On top of engine defaults; blanks dropped
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
        cred_broker=cred_broker,
        cred_broker_port=cred_broker_port,
        sandbox_egress=sandbox_egress,
        egress_proxy_port=egress_proxy_port,
        egress_allow_hosts=egress_allow_hosts,
        sandbox_mem_mb=sandbox_mem_mb,
        sandbox_cpu_percent=sandbox_cpu_percent,
        sandbox_pids_max=sandbox_pids_max,
        sandbox_seccomp=sandbox_seccomp,
        sandbox_seccomp_path=sandbox_seccomp_path,
        sandbox_per_session_uid=sandbox_per_session_uid,
        sandbox_uid_base=sandbox_uid_base,
        sandbox_uid_range=sandbox_uid_range,
        max_sessions_default=max_sessions_default,
        max_live_clients=max_live_clients,
        idle_ttl_sec=idle_ttl_sec,
        shell_ttl_sec=shell_ttl_sec,
        idle_reset_sec=idle_reset_sec,
        cli_update_at=cli_update_at,
        max_concurrent_turns=max_concurrent_turns,
        min_free_mb=min_free_mb,
        archive_retention_days=archive_retention_days,
        voice_transcription=voice_transcription,
        voice_model=voice_model,
        voice_lang=voice_lang,
        voice_max_seconds=voice_max_seconds,
        voice_model_path=voice_model_path,
        extra_blocked_keywords=extra_blocked_keywords,
        max_bot_token=max_bot_token,
        max_api_base=max_api_base,
        max_ca_bundle=max_ca_bundle,
    )
