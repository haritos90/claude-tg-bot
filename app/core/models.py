"""Model and effort catalog taken from the Claude Code CLI.

- Only hardcoded: max-effort permission, hidden families, pinned prefix
- Aliases are stored; the CLI resolves the newest model
- `initialize` lists models, resolved ids, supported effort levels
- `get_settings` reports applied effort; default learned per model
- Persisted in kv, so menus survive restarts
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

# Prefix marking a pinned version id, not a family alias.
# - The CLI catalog has no alias/pinned flag
# - Concrete ids start with `claude-`; aliases never do
_PINNED_PREFIX = "claude-"
# Possible model value shape before any catalog is known.
_SANE_VALUE_RE = re.compile(r"^[a-z0-9][a-z0-9._\-]*(\[1m\])?$")
_KV_CATALOG = "cli_model_catalog"
# Model families withheld from every user, owner included.
# - Offering one needs a per-user grant that doesn't exist yet
# - Hidden families never reach the picker or storage
# - An alias resolving to a hidden family is withheld too
# - Previously stored hidden values run as the default model
_HIDDEN_FAMILIES: tuple[str, ...] = ("fable",)
_KV_DEFAULTS = "cli_model_default_effort"
# Source of the stored catalog: `probe` or `session`.
# - Sandboxed CLIs see a dummy credential, reduced list
_KV_SOURCE = "cli_model_catalog_src"

_catalog: list[dict] = []
# True once the catalog came from the host-CLI probe.
# - A session's reduced view then never replaces it
_authoritative = False
# Lowercased model value to its default effort.
# - None means the model takes no effort level
# - Learned from `get_settings`
_default_effort: dict[str, str | None] = {}
_dirty = False


def _picker_filter() -> tuple[str, ...]:
    """MODEL_PICKER narrows which models the /model picker offers.

    - Comma-separated values; empty means every CLI family alias
    """
    raw = os.environ.get("MODEL_PICKER", "")
    return tuple(v.strip().lower() for v in re.split(r"[,\s]+", raw) if v.strip())


def _clean(rows) -> list[dict]:
    """Keep only well-formed rows with a non-empty `value`."""
    out: list[dict] = []
    for r in rows or ():
        if isinstance(r, dict) and isinstance(r.get("value"), str) and r["value"].strip():
            out.append(r)
    return out


def capture(server_info, authoritative: bool = False) -> bool:
    """Adopt the models list from a client's initialize response.

    - Returns True when the catalog changed
    - An empty list never wipes a known catalog
    - `authoritative` marks the host-CLI probe, which sees real credentials
    - Session captures only fill in until a probe result arrives
    """
    global _catalog, _dirty, _authoritative
    rows = _clean((server_info or {}).get("models") if isinstance(server_info, dict) else None)
    if not rows:
        return False
    if _authoritative and not authoritative:
        return False
    if rows == _catalog and _authoritative == bool(authoritative):
        return False
    _catalog = rows
    _authoritative = _authoritative or bool(authoritative)
    _dirty = True
    logger.info("CLI model catalog: %s", ", ".join(
        f"{r['value']}→{r.get('resolvedModel') or r['value']}" for r in rows))
    return True


def note_applied(value: str | None, applied, explicit_effort: str | None) -> None:
    """Learn a model's default effort from `get_settings`.

    - Only valid when the session set no explicit level
    - None when the model takes no effort level
    """
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
    """Load the persisted catalog and learned defaults at startup."""
    global _catalog, _default_effort, _authoritative
    from app.storage import db  # lazy: keeps module importable without db
    raw = await db.get_kv(_KV_CATALOG)
    if raw:
        try:
            rows = _clean(json.loads(raw))
        except (ValueError, TypeError):
            rows = []
        if rows and not _catalog:
            _catalog = rows
            # A probe catalog stays authoritative across restarts.
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
    """Persist the catalog and learned defaults if changed."""
    global _dirty
    if not _dirty:
        return
    from app.storage import db
    await db.set_kv(_KV_CATALOG, json.dumps(_catalog, ensure_ascii=False))
    await db.set_kv(_KV_SOURCE, "probe" if _authoritative else "session")
    await db.set_kv(_KV_DEFAULTS, json.dumps(_default_effort, ensure_ascii=False))
    _dirty = False


def entries() -> list[dict]:
    """Return catalog rows in CLI order; empty before first capture."""
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
    """True for a pinned version id, not a family alias."""
    return bool(value) and str(value).lower().startswith(_PINNED_PREFIX)


def _is_alias(row: dict) -> bool:
    return not is_pinned(row["value"])


def _id_version(model_id: str | None) -> str:
    """Return the version a concrete model id carries.

    - `claude-opus-5-5` gives `5.5`; date suffixes are dropped
    - Empty string for an alias or versionless id
    """
    if not is_pinned(model_id):
        return ""
    toks = str(model_id).lower().split("[", 1)[0].split("-")[1:]
    return ".".join(t for t in toks if t.isdigit() and len(t) < 8)


def _display_name(row: dict) -> str:
    """Return a row's display name, adding the version if missing.

    - A family-only name takes its version from the resolved id
    - Other names, like the default row, stay unchanged
    """
    name = str(row.get("displayName") or "")
    rid = str(row.get("resolvedModel") or "").lower()
    if name and not any(ch.isdigit() for ch in name) and name.lower() in rid:
        ver = _id_version(rid)
        if ver:
            return f"{name} {ver}"
    return name


def is_hidden(value: str | None) -> bool:
    """True when the value belongs to a withheld family.

    - Also true when its catalog resolution is withheld
    """
    if not value:
        return False
    row = _row(value)
    names = [value] + ([row.get("resolvedModel")] if row else [])
    return any(fam in str(n).lower() for n in names if n for fam in _HIDDEN_FAMILIES)


def picker_values(fallback: tuple[str, ...] = ()) -> list[str]:
    """Return the model values the /model picker offers.

    - CLI order; pinned ids and disabled rows are left out
    - Narrowed by MODEL_PICKER when set
    - Before any catalog is known: only `fallback`
    """
    vals = [r["value"] for r in _catalog
            if _is_alias(r) and not r.get("disabled") and not is_hidden(r["value"])]
    if not vals:
        return [v for v in fallback if v]
    only = _picker_filter()
    if only:
        vals = [v for v in vals if v.lower() in only] or vals
    return vals


def is_selectable(value: str | None) -> bool:
    """True for a value storable as a session model.

    - Any non-disabled catalog row, alias or pinned id
    - Without a catalog, any well-formed value passes
    """
    if not value or is_hidden(value):  # withheld family is never selectable
        return False
    row = _row(value)
    if row is not None:
        return not row.get("disabled")
    return not _catalog and bool(_SANE_VALUE_RE.match(value.lower()))


def match(arg: str | None) -> str | None:
    """Resolve a typed /model argument to its stored value.

    - Case-insensitive; returns catalog spelling, or None
    """
    if not arg:
        return None
    row = _row(arg.strip())
    if row is not None:
        return None if (row.get("disabled") or is_hidden(row["value"])) else row["value"]
    low = arg.strip().lower()
    return low if is_selectable(low) else None


def resolve(value: str | None) -> str | None:
    """Return the concrete model id a stored value runs as.

    - Falls back to the value itself when unknown
    """
    row = _row(value)
    if row is not None and row.get("resolvedModel"):
        return row["resolvedModel"]
    return value


def label(value: str | None) -> str:
    """Return the menu label for a stored value.

    - Alias shows its resolved display name
    - Pinned id gets a pin prefix
    - Kept short: picker buttons sit three per row
    """
    if not value:
        return ""
    row = _row(value)
    if row is None or not row.get("displayName"):
        return value
    if not _is_alias(row):
        return f"📌 {_display_name(row)}"
    return _display_name(row)


def runs_as_label(value: str | None, resolved: str | None = None) -> str:
    """Display name of the model a value runs as.

    - `resolved` is the CLI-reported id, else the catalog's
    - Name comes from the family alias row matching the id
    - Falls back to `label`
    """
    rid = (resolved or resolve(value) or "").lower().split("[", 1)[0]  # drop a [1m] suffix
    if rid:
        for r in _catalog:
            if (_is_alias(r) and r.get("displayName")
                    and str(r.get("resolvedModel") or "").lower() == rid
                    and r["value"].lower() in rid):
                return _display_name(r)
        row = _row(rid)
        if row is not None and row.get("displayName"):
            return label(row["value"])
    return label(value)


def effort_levels(value: str | None) -> list[str]:
    """Return the effort levels the CLI lists for a model.

    - Empty when the model takes none
    - Unknown value: union over the whole catalog
    """
    row = _row(value)
    if row is not None:
        lv = row.get("supportedEffortLevels") if row.get("supportsEffort", True) else None
        return [x for x in (lv or []) if isinstance(x, str) and x]
    return all_effort_levels()


def all_effort_levels() -> list[str]:
    """Return every effort level any model supports, first-seen order."""
    out: list[str] = []
    for r in _catalog:
        for x in r.get("supportedEffortLevels") or []:
            if isinstance(x, str) and x and x not in out:
                out.append(x)
    return out


def effort_below_max(value: str | None) -> str | None:
    """Return the effort level just below `max` for a model.

    - Used to step down users without the max grant
    - None means fall back to the model's default
    - `max` is a permission, so the bot knows its name
    """
    levels = effort_levels(value)
    if "max" in levels:
        i = levels.index("max")
        return levels[i - 1] if i > 0 else None
    return levels[-1] if levels else None


def default_effort(value: str | None) -> str | None:
    """Return the effort the CLI applies when none is set.

    - As last learned from a session; None if unknown
    """
    return _default_effort.get((value or "").lower())


def effective_effort(value: str | None, explicit: str | None) -> str | None:
    """Return the effort a session runs at.

    - Explicit level first, else the model's learned default
    - None when the model takes no effort level
    """
    if not effort_levels(value) and _row(value) is not None:
        return None
    return explicit or default_effort(value)


def family_alias(model_id: str | None) -> str | None:
    """Return the family alias a pinned id belongs to.

    - Uses the first alphabetic token of the id
    - Validated against catalog aliases when known; else None
    """
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
    """Read the catalog and default efforts from the host CLI.

    - Uses a throwaway client so menus are right pre-turn
    - Runs at startup and after every CLI update
    - Local control requests only: no prompt, no tokens
    - Environment drops API-key variables; returns True if read
    """
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
        capture(await client.get_server_info(), authoritative=True)  # probe sees the real credential
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
