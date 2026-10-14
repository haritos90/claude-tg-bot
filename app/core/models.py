"""Model + effort catalog taken from the Claude Code CLI (#411).

The bot hardcodes no model and no effort level. The deliberate exceptions, each recorded as
a decision record: the ``max`` effort level is a separate per-user permission (decision-20,
handlers._may_max_effort); the Fable family is withheld from everyone (decision-21,
``_HIDDEN_FAMILIES``); a ``claude-`` prefix marks a pinned version id (decision-19,
``_PINNED_PREFIX``). The context window is each model's own — no 1M switch, no family list
(decision-26; it replaced the decision-22 list). Everything else comes from the CLI
(decision-19):

* the CLI's ``initialize`` response lists the models this account can pick — family aliases
  (``opus``, ``sonnet``, ``fable``, ``haiku``, ``default``) plus pinned version ids
  (``claude-opus-4-8`` …) — each with the concrete id it currently resolves to, a display
  name and the effort levels it supports::

      {"value": "opus", "resolvedModel": "claude-opus-5-5", "displayName": "Opus 5.5",
       "supportsEffort": true, "supportedEffortLevels": ["low", "medium", …]}

* the CLI's ``get_settings`` control request reports the effort a session ACTUALLY runs at
  (``applied.effort``) — with no explicit level that is the model's own default (e.g. medium
  for Opus 5.5), which :func:`note_applied` remembers per model.

Sessions store and pass the ALIAS, so the CLI resolves it to the newest model of that family:
a model release reaches every session with a CLI update (``cli_update``), no bot change.

Both are captured from every client connect (``engine._ensure_client``) and persisted in kv
(:func:`flush`, called by the reaper sweep) so menus have them right after a restart
(:func:`load`). Before the very first capture the picker offers only the configured default.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile

logger = logging.getLogger("models")

# A catalog value that is a pinned version id rather than a family alias. decision-19: the CLI's
# catalog carries no alias/pinned flag; every concrete model id it lists starts with "claude-"
# and no alias does, so the prefix is the one structural rule taken from the CLI's id scheme.
_PINNED_PREFIX = "claude-"
# What a model value may look like before any catalog is known (alias, id, [1m] suffix).
_SANE_VALUE_RE = re.compile(r"^[a-z0-9][a-z0-9._\-]*(\[1m\])?$")
_KV_CATALOG = "cli_model_catalog"
# #420 / decision-21: model families withheld from EVERY user, the owner included — a named
# exception to "nothing is hardcoded", like the max-effort grant (decision-20). Offering Fable is
# a budget decision about the host's shared subscription (meant for hosts on a Max plan) that
# needs its own per-user grant (#421); until that exists, nobody can pick it. A hidden family
# never reaches the picker and cannot be stored; an alias that currently RESOLVES to one (e.g.
# the CLI's "default", should it ever recommend Fable) is withheld as well, and a value stored
# before the family was hidden runs as the default model (SessionManager._effective_settings).
_HIDDEN_FAMILIES: tuple[str, ...] = ("fable",)
_KV_DEFAULTS = "cli_model_default_effort"
# #426: where the stored catalog came from — "probe" (the host CLI with the account's real
# credential) or "session" (a sandboxed client, whose CLI sees only the broker's dummy credential
# and reports a reduced list: family names without versions, no pinned ids).
_KV_SOURCE = "cli_model_catalog_src"

_catalog: list[dict] = []
# #426: True once the catalog came from the host-CLI probe — a session's reduced view then never
# replaces it (capture).
_authoritative = False
# lower-cased catalog value → the effort the CLI applies when none is set (None = the model
# takes no effort level). Learned from get_settings (note_applied).
_default_effort: dict[str, str | None] = {}
_dirty = False


def _picker_filter() -> tuple[str, ...]:
    """MODEL_PICKER (comma-separated values) narrows which catalog rows the /model picker
    offers — e.g. to keep a costlier family out of other users' reach. Empty (the default)
    = every family alias the CLI offers."""
    raw = os.environ.get("MODEL_PICKER", "")
    return tuple(v.strip().lower() for v in re.split(r"[,\s]+", raw) if v.strip())


def _clean(rows) -> list[dict]:
    """Keep only well-formed rows (a dict with a non-empty string ``value``)."""
    out: list[dict] = []
    for r in rows or ():
        if isinstance(r, dict) and isinstance(r.get("value"), str) and r["value"].strip():
            out.append(r)
    return out


def capture(server_info, authoritative: bool = False) -> bool:
    """Adopt the ``models`` list from a client's initialize response (``get_server_info()``).
    Returns True when it changed the catalog (marked for :func:`flush`). An empty or absent
    list never wipes a known catalog — an older CLI may simply not report one.

    #426: ``authoritative`` marks the host-CLI probe (:func:`probe`), whose CLI holds the
    account's real credential. A sandboxed session's CLI sees only the broker's dummy credential
    and reports a reduced list (family names without versions, no pinned ids), so a session
    capture only fills in until the first probe result and never replaces it — the two views
    used to overwrite each other on every connect (labels flipping between "Opus" and
    "Opus 5.5")."""
    global _catalog, _dirty, _authoritative
    rows = _clean((server_info or {}).get("models") if isinstance(server_info, dict) else None)
    if not rows:
        return False
    if _authoritative and not authoritative:
        return False
    if rows == _catalog and _authoritative == bool(authoritative):
        return False
    # was (#411): if not rows or rows == _catalog: return False — then adopt unconditionally
    _catalog = rows
    _authoritative = _authoritative or bool(authoritative)
    _dirty = True
    logger.info("CLI model catalog: %s", ", ".join(
        f"{r['value']}→{r.get('resolvedModel') or r['value']}" for r in rows))
    return True


def note_applied(value: str | None, applied, explicit_effort: str | None) -> None:
    """Learn a model's DEFAULT effort from a session's ``get_settings`` ``applied`` block: with
    no explicit level set, ``applied.effort`` is what the CLI picks for that model (None when
    the model takes no effort level). A session with an explicit level teaches nothing."""
    global _dirty
    if explicit_effort or not value or not isinstance(applied, dict) or "effort" not in applied:
        return
    eff = applied.get("effort")
    eff = eff if isinstance(eff, str) and eff else None
    key = value.lower()
    if _default_effort.get(key, "?") != eff:
        _default_effort[key] = eff
        _dirty = True


async def load() -> None:
    """Load the last persisted catalog + learned defaults from kv (startup)."""
    global _catalog, _default_effort, _authoritative
    from app.storage import db  # lazy: keeps this module importable without a db
    raw = await db.get_kv(_KV_CATALOG)
    if raw:
        try:
            rows = _clean(json.loads(raw))
        except (ValueError, TypeError):
            rows = []
        if rows and not _catalog:
            _catalog = rows
            # #426: a probe catalog stays authoritative across restarts.
            _authoritative = (await db.get_kv(_KV_SOURCE)) == "probe"
    raw = await db.get_kv(_KV_DEFAULTS)
    if raw:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict) and not _default_effort:
            _default_effort = {str(k).lower(): (v if isinstance(v, str) and v else None)
                               for k, v in data.items()}


async def flush() -> None:
    """Persist the catalog + learned defaults if they changed since the last flush."""
    global _dirty
    if not _dirty:
        return
    from app.storage import db
    await db.set_kv(_KV_CATALOG, json.dumps(_catalog, ensure_ascii=False))
    await db.set_kv(_KV_SOURCE, "probe" if _authoritative else "session")  # #426
    await db.set_kv(_KV_DEFAULTS, json.dumps(_default_effort, ensure_ascii=False))
    _dirty = False


def entries() -> list[dict]:
    """The current catalog rows (CLI order); [] before the first capture."""
    return list(_catalog)


def _row(value: str | None) -> dict | None:
    if not value:
        return None
    low = value.lower()
    for r in _catalog:
        if r["value"].lower() == low:
            return r
    return None


def is_pinned(value: str | None) -> bool:
    """True for a pinned version id (``claude-opus-4-8``) rather than a family alias."""
    return bool(value) and str(value).lower().startswith(_PINNED_PREFIX)


def _is_alias(row: dict) -> bool:
    # was: return not row["value"].lower().startswith(_PINNED_PREFIX)  — #422: via is_pinned
    return not is_pinned(row["value"])


def _id_version(model_id: str | None) -> str:
    """#426: the version a concrete id carries — ``claude-opus-5-5`` → ``5.5``,
    ``claude-haiku-4-5-20251001`` → ``4.5`` (a date suffix is dropped), ``claude-3-5-sonnet-…``
    → ``3.5``; "" for an alias or an id without one."""
    if not is_pinned(model_id):
        return ""
    toks = str(model_id).lower().split("[", 1)[0].split("-")[1:]
    return ".".join(t for t in toks if t.isdigit() and len(t) < 8)


def _display_name(row: dict) -> str:
    """#426: a row's display name. When the CLI names only the family ("Opus" — the reduced
    catalog a sandboxed CLI reports), the version comes from the id it resolves to
    ("Opus 5.5"); a name that is not the family (the CLI's "Default (recommended)") stays."""
    name = str(row.get("displayName") or "")
    rid = str(row.get("resolvedModel") or "").lower()
    if name and not any(ch.isdigit() for ch in name) and name.lower() in rid:
        ver = _id_version(rid)
        if ver:
            return f"{name} {ver}"
    return name


def is_hidden(value: str | None) -> bool:
    """#420: True when ``value`` — or what the catalog says it resolves to — belongs to a
    withheld family."""
    if not value:
        return False
    row = _row(value)
    names = [value] + ([row.get("resolvedModel")] if row else [])
    return any(fam in str(n).lower() for n in names if n for fam in _HIDDEN_FAMILIES)


def picker_values(fallback: tuple[str, ...] = ()) -> list[str]:
    """Values the /model picker offers: the CLI's aliases — its own ``default`` row (the model
    Claude Code recommends for the account) and the family aliases — in CLI order, pinned
    version ids and disabled rows left out, optionally narrowed by MODEL_PICKER. Before any
    catalog is known: just ``fallback`` (the configured default model)."""
    vals = [r["value"] for r in _catalog
            if _is_alias(r) and not r.get("disabled") and not is_hidden(r["value"])]  # #420
    if not vals:
        return [v for v in fallback if v]
    only = _picker_filter()
    if only:
        vals = [v for v in vals if v.lower() in only] or vals
    return vals


def is_selectable(value: str | None) -> bool:
    """True for a value the bot may store as a session model: any non-disabled catalog row
    (alias or pinned id). Before any catalog is known, any well-formed value (the CLI is the
    judge on the next turn)."""
    if not value or is_hidden(value):  # #420: a withheld family is never selectable
        return False
    row = _row(value)
    if row is not None:
        return not row.get("disabled")
    return not _catalog and bool(_SANE_VALUE_RE.match(value.lower()))


def match(arg: str | None) -> str | None:
    """Resolve a typed ``/model <arg>`` to the value to store (catalog spelling), or None.
    Accepts a family alias or a pinned id the CLI lists, case-insensitively."""
    if not arg:
        return None
    row = _row(arg.strip())
    if row is not None:
        return None if (row.get("disabled") or is_hidden(row["value"])) else row["value"]  # #420
    low = arg.strip().lower()
    return low if is_selectable(low) else None


def resolve(value: str | None) -> str | None:
    """The concrete model id a stored value currently runs as (``opus`` → ``claude-opus-5-5``),
    or the value itself when the catalog doesn't know it (a pinned id resolves to itself)."""
    row = _row(value)
    if row is not None and row.get("resolvedModel"):
        return row["resolvedModel"]
    return value


def label(value: str | None) -> str:
    """Menu label for a stored value: the display name of what a family alias resolves to
    right now (``opus`` → ``Opus 5.5``, ``Opus 6`` after the next release), ``📌`` + the name
    for a pinned version id (it never moves), else the raw value. Short on purpose — picker
    buttons sit three to a row."""
    if not value:
        return ""
    row = _row(value)
    if row is None or not row.get("displayName"):
        return value
    # #426: via _display_name (was row["displayName"] as is).
    if not _is_alias(row):
        return f"📌 {_display_name(row)}"
    return _display_name(row)


def runs_as_label(value: str | None, resolved: str | None = None) -> str:
    """#422: the display name of the model a value actually runs as — "Opus 5.5" for ``opus``
    AND for the CLI's ``default`` while that resolves to Opus 5.5. ``resolved`` is the concrete
    id the CLI reported for the session (get_settings), else the catalog's resolution. The name
    comes from the family alias row whose alias appears in the resolved id, so no family is
    named here; a pinned id uses its own row. Falls back to :func:`label`."""
    rid = (resolved or resolve(value) or "").lower().split("[", 1)[0]  # drop a [1m] suffix
    if rid:
        for r in _catalog:
            if (_is_alias(r) and r.get("displayName")
                    and str(r.get("resolvedModel") or "").lower() == rid
                    and r["value"].lower() in rid):
                return _display_name(r)  # #426 (was str(r["displayName"]))
        row = _row(rid)
        if row is not None and row.get("displayName"):
            return label(row["value"])
    return label(value)


def effort_levels(value: str | None) -> list[str]:
    """Effort levels the CLI lists for a model value (its ``supportedEffortLevels``); [] when
    the model takes none. For a value the catalog doesn't know: the union over the catalog."""
    row = _row(value)
    if row is not None:
        lv = row.get("supportedEffortLevels") if row.get("supportsEffort", True) else None
        return [x for x in (lv or []) if isinstance(x, str) and x]
    return all_effort_levels()


def all_effort_levels() -> list[str]:
    """Every effort level any catalog model supports, in first-seen order."""
    out: list[str] = []
    for r in _catalog:
        for x in r.get("supportedEffortLevels") or []:
            if isinstance(x, str) and x and x not in out:
                out.append(x)
    return out


def effort_below_max(value: str | None) -> str | None:
    """#420 / decision-20: the level just under ``max`` in the CLI's list for this model (what
    a user without the max grant is stepped down to); None when the model has no such level,
    i.e. fall back to the model's default. ``max`` is the one effort name the bot knows, because
    it is a permission, not a model property."""
    levels = effort_levels(value)
    if "max" in levels:
        i = levels.index("max")
        return levels[i - 1] if i > 0 else None
    return levels[-1] if levels else None


def default_effort(value: str | None) -> str | None:
    """The effort the CLI applies to a model when none is set — as last learned from a
    session on it (note_applied); None when unknown or when the model takes none."""
    return _default_effort.get((value or "").lower())


def effective_effort(value: str | None, explicit: str | None) -> str | None:
    """The effort a session runs at: its explicit level, else the model's learned default.
    None when the model takes no effort level (or nothing is known yet)."""
    if not effort_levels(value) and _row(value) is not None:
        return None
    return explicit or default_effort(value)


def family_alias(model_id: str | None) -> str | None:
    """The family alias a pinned ``claude-…`` id belongs to (``claude-opus-4-8`` → ``opus``,
    ``claude-3-5-sonnet-20241022`` → ``sonnet``): its first word token. Validated against the
    catalog's aliases when one is known; None for anything that is not a pinned id."""
    if not model_id or not model_id.lower().startswith(_PINNED_PREFIX):
        return None
    fam = next((tok for tok in model_id.lower().split("[", 1)[0].split("-")[1:]
                if tok.isalpha()), None)
    if not fam:
        return None
    aliases = {r["value"].lower() for r in _catalog if _is_alias(r)}
    if aliases and fam not in aliases:
        return None
    return fam


async def probe(cli_path: str | None, timeout: float = 60.0) -> bool:
    """Read the catalog — and every family's default effort — straight from the CLI with a
    throwaway client, so menus are right before the first user turn (startup, and after every
    CLI update). No prompt is sent: ``initialize`` (the model list) plus, per alias, a
    ``set_model`` + ``get_settings`` pair — local control requests, no API call, no tokens.
    Runs the given (host) CLI with the bot's own environment minus the API-key variables
    (subscription only) and no settings sources. Returns True when a catalog was read."""
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient  # lazy: heavy import
    if not cli_path or not os.path.exists(cli_path):
        return False
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    env["CLAUDE_CODE_DISABLE_WORKFLOWS"] = "1"
    workdir = tempfile.mkdtemp(prefix="cli-probe-")
    client = ClaudeSDKClient(ClaudeAgentOptions(
        cli_path=cli_path, cwd=workdir, setting_sources=[], tools=[], allowed_tools=[],
        env=env))
    try:
        await asyncio.wait_for(client.connect(), timeout)
        capture(await client.get_server_info(), authoritative=True)  # #426: the account's view
        query = client._query
        for row in list(_catalog):
            if not _is_alias(row) or row.get("disabled"):
                continue
            try:
                await query._send_control_request(
                    {"subtype": "set_model", "model": row["value"]}, timeout=15.0)
                resp = await query._send_control_request({"subtype": "get_settings"},
                                                         timeout=15.0)
            except Exception:
                continue
            note_applied(row["value"], (resp or {}).get("applied"), None)
        return bool(_catalog)
    finally:
        try:
            await asyncio.wait_for(client.disconnect(), 20.0)
        except Exception:
            pass
        shutil.rmtree(workdir, ignore_errors=True)
