"""Tests for CLI-driven catalog, update, naming, and streaming features.

- model/effort catalog; daily CLI update with graceful recycling
- untitled-session naming and follow-up injection
- single-message rich commit and opt-in draft table hold
- withheld model family and thinking-tag model line
- pure pytest: fakes only, no network or CLI
"""

import asyncio
import contextlib
import json
import os
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import i18n
from app.core import cli_update, engine, models, sessions
from app.storage import db, usage
from app.telegram import markup, streamer

CATALOG = [
    {"value": "default", "resolvedModel": "claude-opus-5-5", "displayName": "Default (recommended)",
     "supportsEffort": True, "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
    {"value": "opus", "resolvedModel": "claude-opus-5-5", "displayName": "Opus 5.5",
     "supportsEffort": True, "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
    {"value": "sonnet", "resolvedModel": "claude-sonnet-5-5", "displayName": "Sonnet 5.5",
     "supportsEffort": True, "supportedEffortLevels": ["low", "medium", "high"]},
    {"value": "haiku", "resolvedModel": "claude-haiku-4-5-20251001", "displayName": "Haiku 4.5"},
    {"value": "claude-opus-4-8", "resolvedModel": "claude-opus-4-8", "displayName": "Opus 4.8",
     "supportsEffort": True, "supportedEffortLevels": ["low", "medium", "high", "max"]},
]


@pytest.fixture(autouse=True)
def _fresh_catalog(monkeypatch):
    """Every test starts from an empty catalog and leaves none."""
    monkeypatch.setattr(models, "_catalog", [])
    monkeypatch.setattr(models, "_authoritative", False)
    monkeypatch.setattr(models, "_default_effort", {})
    monkeypatch.setattr(models, "_dirty", False)
    monkeypatch.delenv("MODEL_PICKER", raising=False)


# ---- the model catalog ----

def test_capture_adopts_catalog_and_ignores_empty():
    assert models.capture({"models": CATALOG}) is True
    assert models.capture({"models": CATALOG}) is False          # unchanged: no-op
    assert models.capture({"models": []}) is False               # an empty list never wipes it
    assert models.capture(None) is False
    assert [r["value"] for r in models.entries()] == [r["value"] for r in CATALOG]


def test_picker_lists_aliases_only_and_honours_model_picker(monkeypatch):
    assert models.picker_values(fallback=("opus",)) == ["opus"]  # no catalog: the fallback only
    models.capture({"models": CATALOG})
    assert models.picker_values() == ["default", "opus", "sonnet", "haiku"]  # no pinned ids
    monkeypatch.setenv("MODEL_PICKER", "opus, sonnet")
    assert models.picker_values() == ["opus", "sonnet"]


def test_match_resolve_label_and_selectable():
    assert models.match("Opus") == "opus"                         # no catalog: sane value passes
    models.capture({"models": CATALOG})
    assert models.match("OPUS") == "opus"
    assert models.match("claude-opus-4-8") == "claude-opus-4-8"
    assert models.match("gpt-5") is None                          # not offered by the CLI
    assert models.resolve("opus") == "claude-opus-5-5"
    assert models.resolve("claude-x-1") == "claude-x-1"           # unknown: itself
    assert models.label("opus") == "Opus 5.5"
    assert models.label("claude-opus-4-8") == "📌 Opus 4.8"       # pinned ids are marked
    assert models.is_selectable("sonnet") and not models.is_selectable("nope")


def test_effort_levels_defaults_and_effective_effort():
    models.capture({"models": CATALOG})
    assert models.effort_levels("sonnet") == ["low", "medium", "high"]
    assert models.effort_levels("haiku") == []                    # takes no effort level
    assert models.all_effort_levels() == ["low", "medium", "high", "xhigh", "max"]
    assert models.default_effort("opus") is None                  # not learned yet
    models.note_applied("opus", {"model": "claude-opus-5-5", "effort": "medium"}, None)
    models.note_applied("opus", {"effort": "high"}, "high")       # explicit level teaches nothing
    assert models.default_effort("opus") == "medium"
    assert models.effective_effort("opus", None) == "medium"
    assert models.effective_effort("opus", "xhigh") == "xhigh"
    assert models.effective_effort("haiku", "max") is None        # model without effort


# ---- withheld family and max step-down ----

WITHHELD = [
    {"value": "fable", "resolvedModel": "claude-fable-5-1", "displayName": "Fable 5.1",
     "supportsEffort": True, "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
    {"value": "claude-fable-5", "resolvedModel": "claude-fable-5", "displayName": "Fable 5",
     "supportsEffort": True, "supportedEffortLevels": ["low", "medium", "high", "max"]},
]


def test_withheld_family_is_never_offered_or_selectable():
    models.capture({"models": CATALOG + WITHHELD})
    assert models.picker_values() == ["default", "opus", "sonnet", "haiku"]
    assert models.match("fable") is None and models.match("Claude-Fable-5") is None
    assert not models.is_selectable("fable") and not models.is_selectable("claude-fable-5")
    assert models.is_hidden("fable") and not models.is_hidden("opus")
    assert not models.is_hidden(None)


def test_alias_resolving_to_a_withheld_family_is_withheld():
    rows = [dict(CATALOG[0], resolvedModel="claude-fable-5-1")] + CATALOG[1:]
    models.capture({"models": rows})
    assert models.is_hidden("default")
    assert "default" not in models.picker_values() and models.match("default") is None


def test_effort_below_max_follows_the_cli_list():
    assert models.effort_below_max("opus") is None                # no catalog: model default
    models.capture({"models": CATALOG})
    assert models.effort_below_max("opus") == "xhigh"
    assert models.effort_below_max("claude-opus-4-8") == "high"   # this model has no xhigh
    assert models.effort_below_max("sonnet") == "high"            # no max: its top level
    assert models.effort_below_max("haiku") is None               # takes no effort level


def test_family_alias_for_migration():
    assert models.family_alias("claude-opus-4-8") == "opus"       # no catalog: the word token
    assert models.family_alias("claude-3-5-sonnet-20241022") == "sonnet"
    assert models.family_alias("opus") is None                    # already an alias
    models.capture({"models": CATALOG})
    assert models.family_alias("claude-fable-5") is None          # family the catalog lacks


def test_load_and_flush_roundtrip(monkeypatch):
    store: dict = {}

    async def _get(key, default=None):
        return store.get(key, default)

    async def _set(key, value):
        store[key] = value

    monkeypatch.setattr(db, "get_kv", _get)
    monkeypatch.setattr(db, "set_kv", _set)
    models.capture({"models": CATALOG})
    models.note_applied("sonnet", {"effort": "medium"}, None)
    asyncio.run(models.flush())
    monkeypatch.setattr(models, "_catalog", [])
    monkeypatch.setattr(models, "_default_effort", {})
    asyncio.run(models.load())
    assert models.label("sonnet") == "Sonnet 5.5" and models.default_effort("sonnet") == "medium"


def test_migrate_model_ids_to_aliases_runs_once(tmp_path):
    async def _t():
        await db.init_db(str(tmp_path / "m.db"))
        k = await db.allocate_dm_session(5, "s", "claude-opus-4-8", "/tmp", mode="chat")
        await db.set_user_default(5, "model", "claude-sonnet-4-6")
        n1 = await db.migrate_model_ids_to_aliases(models.family_alias)
        st = await db.get_thread(k)
        ud = await db.get_user_default(5, "model")
        await db.set_model(k, "claude-opus-4-8")                  # a deliberate pin afterwards
        n2 = await db.migrate_model_ids_to_aliases(models.family_alias)
        st2 = await db.get_thread(k)
        await db.close_db()
        return n1, st.model, ud, n2, st2.model
    n1, model, ud, n2, model2 = asyncio.run(_t())
    assert (n1, model, ud) == (2, "opus", "sonnet")
    assert (n2, model2) == (0, "claude-opus-4-8")                 # one-time: the pin survives


def test_maybe_t_is_opportunistic():
    assert i18n.maybe_t("effort.level.medium", "ru", "medium") == i18n.CATALOG["effort.level.medium"]["ru"]
    assert i18n.maybe_t("effort.level.turbo", "ru", "turbo") == "turbo"   # unknown: as given


# ---- CLI update and stage ----

def _fake_cli(tmp_path, version, script_body="exit 0"):
    vdir = tmp_path / "versions"
    vdir.mkdir(exist_ok=True)
    exe = vdir / version
    exe.write_text(f"#!/bin/sh\n{script_body}\n")
    exe.chmod(0o755)
    link = tmp_path / "claude"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(exe)
    return str(link)


def test_stage_copies_only_on_change(tmp_path, monkeypatch):
    link = _fake_cli(tmp_path, "2.1.288")
    monkeypatch.setattr(cli_update.shutil, "which", lambda name: link)
    dst = str(tmp_path / "staged-claude")
    assert cli_update.stage(dst).endswith("2.1.288")
    assert cli_update.stage(dst) is None                          # same source: no copy
    assert cli_update.version_of(cli_update.staged_source(dst)) == "2.1.288"
    _fake_cli(tmp_path, "2.1.290")
    assert cli_update.stage(dst).endswith("2.1.290")              # host moved: re-staged
    assert os.access(dst, os.X_OK)


def test_update_and_stage_reports_versions(tmp_path, monkeypatch):
    link = _fake_cli(tmp_path, "2.1.288", 'echo "Claude Code is up to date (2.1.288)"')
    monkeypatch.setattr(cli_update.shutil, "which", lambda name: link)
    monkeypatch.setattr(cli_update, "STAGED_PATH", str(tmp_path / "staged"))
    monkeypatch.setattr(cli_update, "stage", lambda dst=None: None)
    res = cli_update.update_and_stage(stage_jail=True)
    assert res.ok and res.before == res.after == "2.1.288" and not res.changed
    assert "up to date" in res.detail


# ---- naming tiers and untitled sweep ----

def test_first_words_and_reply_topic():
    assert sessions._first_words("u up?") == "u up?"
    assert sessions._first_words("Recap our conversation so far") is None   # injected prompt
    assert sessions._first_words("  ...  ") is None
    assert len(sessions._first_words("word " * 30)) <= sessions._BUTTON_NAME_MAX
    reply = ("This is **Chemsearch YIELD** — a professional penetrating aerosol lubricant. "
             + "More details. " * 20)
    assert sessions._topic_from_reply(reply) == "Chemsearch YIELD"
    assert sessions._topic_from_reply("I'm here 🙂 How can I help?") is None     # probe answer


def _transcript(tmp_path, sid, lines):
    from app.storage import archive
    cwd = tmp_path / "sess" / "work"
    cwd.mkdir(parents=True, exist_ok=True)
    tdir = archive.live_transcript_dir(str(cwd))
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / f"{sid}.jsonl").write_text(
        "\n".join(json.dumps(o, ensure_ascii=False) for o in lines) + "\n", encoding="utf-8")
    return str(cwd)


def test_read_name_fallbacks(tmp_path):
    long_reply = "That is an **ergonomic baby carrier backpack** — handy. " + "x " * 200
    cwd = _transcript(tmp_path, "s1", [
        {"type": "user", "message": {"content": [{"type": "image"}]}},     # photo, no caption
        {"type": "assistant", "message": {"content": [{"type": "text", "text": long_reply}]}},
        {"type": "user", "message": {"content": "What's this?"}},
    ])
    first, topic = sessions._read_name_fallbacks(cwd, "s1")
    assert first == "What's this?"
    assert topic == "Ergonomic baby carrier backpack"


def test_tidy_untitled_names_probe_and_archives_empty(monkeypatch):
    sm = sessions.SessionManager(bot=SimpleNamespace(), settings=SimpleNamespace(),
                                 gate=SimpleNamespace())
    page = [
        {"thread_id": -1, "name": "Not named yet", "name_auto": True, "favorite": False},  # keep
        {"thread_id": -2, "name": "Not named yet", "name_auto": True, "favorite": False},  # probe
        {"thread_id": -3, "name": i18n.t("session.default_name_chat", "ru"), "name_auto": True,
         "favorite": False},
        {"thread_id": -4, "name": "Real title", "name_auto": True, "favorite": False},
        {"thread_id": -5, "name": "Not named yet", "name_auto": False, "favorite": False},
    ]

    async def _browse(uid, kw, limit=8, offset=0):
        return page, len(page)

    async def _totals(ids):
        return {-2: {"requests": 1}, -3: {"requests": 0}, -4: {"requests": 3}}

    named, disposed = [], []

    async def _derive(key):
        return "u up?" if key == -2 else None

    async def _set_name(tid, name, *, manual=True):
        named.append((tid, name, manual))

    async def _dispose(uid, key, name):
        disposed.append(key)
        return True

    monkeypatch.setattr(db, "browse_threads", _browse)
    monkeypatch.setattr(db, "get_usage_totals_bulk", _totals)
    monkeypatch.setattr(db, "set_session_name", _set_name)
    monkeypatch.setattr(sm, "_derive_session_name", _derive)
    monkeypatch.setattr(sm, "dispose_dm_session", _dispose)
    n, d = asyncio.run(sm.tidy_untitled(7, keep=-1))
    assert named == [(-2, "u up?", False)]                        # used: named by its words
    assert disposed == [-3]                                       # never used: archived
    assert (n, d) == (1, 1)                                       # -4 named, -5 pinned: untouched


def test_tidy_untitled_never_archives_on_read_error(monkeypatch):
    sm = sessions.SessionManager(bot=SimpleNamespace(), settings=SimpleNamespace(),
                                 gate=SimpleNamespace())

    async def _browse(uid, kw, limit=8, offset=0):
        return [{"thread_id": -2, "name": "Not named yet", "name_auto": True}], 1

    async def _totals(ids):
        return {-2: {"requests": 2}}

    async def _boom(key):
        raise OSError("unreadable")

    disposed = []

    async def _dispose(uid, key, name):
        disposed.append(key)
        return True

    monkeypatch.setattr(db, "browse_threads", _browse)
    monkeypatch.setattr(db, "get_usage_totals_bulk", _totals)
    monkeypatch.setattr(sm, "_derive_session_name", _boom)
    monkeypatch.setattr(sm, "dispose_dm_session", _dispose)
    assert asyncio.run(sm.tidy_untitled(7, keep=-1)) == (0, 0) and disposed == []


# ---- follow-up injection ----

def test_inject_requires_active_turn_with_state_events():
    s = engine.ClaudeSession("chat", "opus", None)
    sent = []

    async def _send(prompt, attachments):
        sent.append(prompt)

    s._send_query = _send
    assert asyncio.run(s.inject("more")) is False                 # no client or no turn
    s.client = object()
    s._turn_active = True
    assert asyncio.run(s.inject("more")) is False                 # CLI streams no state events
    s._states_seen = True
    assert asyncio.run(s.inject("more")) is True and sent == ["more"] and s._injected == 1


def _state(name):
    return engine.SystemMessage(subtype="session_state_changed", data={"state": name})


def _aiter(items):
    async def _gen():
        for it in items:
            yield it
    return _gen().__aiter__()


def test_settle_idle_means_folded_in():
    s = engine.ClaudeSession("chat", "opus", None)
    s._injected, s._states_seen = 1, True
    asyncio.run(s._settle_after_result(_aiter([_state("idle")])))
    assert s.followup_pending is False and s._injected == 0 and s._stash == []


def test_settle_new_turn_means_followup_and_is_replayed():
    s = engine.ClaudeSession("chat", "opus", None)
    s._injected, s._states_seen = 1, True
    init = engine.SystemMessage(subtype="init", data={"model": "claude-opus-5-5"})
    asyncio.run(s._settle_after_result(_aiter([_state("running"), init])))
    assert s.followup_pending is True and s._stash == [init]

    class _Client:
        def receive_messages(self):
            async def _gen():
                yield engine.ResultMessage(
                    subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                    num_turns=1, session_id="sid", result="second answer")
            return _gen()

    s.client = _Client()

    async def _ensure():
        return None

    s._ensure_client = _ensure

    async def _collect():
        return [ev async for ev in s.run(None)]

    evs = asyncio.run(_collect())
    assert [e.kind for e in evs][-1] == "result" and evs[-1].text == "second answer"
    assert s.resolved_model == "claude-opus-5-5"                  # the stashed init was replayed


def test_handle_text_injects_into_running_turn(monkeypatch):
    sm = sessions.SessionManager(bot=SimpleNamespace(), settings=SimpleNamespace(
        default_model="opus", base_workdir="/tmp"), gate=SimpleNamespace())
    logged = []

    async def _ensure_thread(*a, **k):
        return SimpleNamespace()

    async def _log(tid, role, text):
        logged.append((role, text))

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(db, "ensure_thread", _ensure_thread)
    monkeypatch.setattr(db, "log_message", _log)
    monkeypatch.setattr(db, "set_kv", _noop)
    rec = sm._record(-9)

    class _Live:
        async def inject(self, text, attachments=None):
            return True

    async def _forever():
        await asyncio.sleep(3600)

    async def _t():
        rec.session = _Live()
        rec.worker = asyncio.ensure_future(_forever())
        try:
            return await sm.handle_text(7, -9, "and also this")
        finally:
            rec.worker.cancel()

    assert asyncio.run(_t()) == sessions.SUBMIT_INJECTED
    assert logged == [("user", "and also this")] and rec.queue.empty()


# ---- one rich message ----

class _RichBot:
    def __init__(self, fail=False):
        self.methods, self.fail = [], fail

    async def __call__(self, method):
        if self.fail:
            raise RuntimeError("rejected")
        self.methods.append(method)

    async def delete_message(self, chat_id, message_id):
        return True


def test_map_block_and_location_maps():
    s = streamer.Streamer(_RichBot(), 1, None)
    block = s._map_block({"lat": 48.8584, "lon": 2.2945, "title": "Eiffel <Tower>", "address": "Paris"})
    assert '<tg-map lat="48.858400" long="2.294500" zoom="15"/>' in block
    assert "<figcaption>Eiffel &lt;Tower&gt; — Paris</figcaption>" in block
    tok = markup.LOCATION_TOKEN
    out = s._location_maps(f"a{tok}b", [{"lat": 1, "lon": 2}])
    assert tok not in out and "<tg-map" in out and out.startswith("a") and out.endswith("b")


def test_commit_rich_embedded_sends_one_message_with_media(monkeypatch):
    monkeypatch.setattr(streamer.svg_image, "render_svg_png", lambda svg: b"\x89PNG-fake")
    bot = _RichBot()
    s = streamer.Streamer(bot, 1, None)
    rich_text = f"Intro {markup.SVG_TOKEN} middle {markup.LOCATION_TOKEN} end"
    ok = asyncio.run(s._commit_rich_embedded(
        rich_text, [{"lat": 1, "lon": 2}], ["<svg/>"], [], "5h: 1%", silent=True))
    assert ok and len(bot.methods) == 1                           # ONE message, no split
    rm = bot.methods[0].rich_message
    assert "![](tg://photo?id=m1)" in rm["markdown"] and "<tg-map" in rm["markdown"]
    assert rm["markdown"].index("Intro") < rm["markdown"].index("tg://photo") < rm["markdown"].index("<tg-map")
    assert rm["media"][0]["id"] == "m1" and rm["media"][0]["media"]["type"] == "photo"
    assert "_5h: 1%_" in rm["markdown"]


def test_commit_rich_embedded_reports_failure_for_fallback(monkeypatch):
    monkeypatch.setattr(streamer.svg_image, "render_svg_png", lambda svg: b"png")
    s = streamer.Streamer(_RichBot(fail=True), 1, None)
    assert asyncio.run(s._commit_rich_embedded(
        f"x{markup.SVG_TOKEN}", [], ["<svg/>"], [], "", silent=True)) is False


# ---- opt-in draft table hold ----

@pytest.mark.parametrize("text,body,rows", [
    ("Intro\n\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 |", "Intro\n", 1),
    ("Intro\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", "Intro\n", 1),
    ("Intro\n\n| a | b |", "Intro\n", 0),
    ("Here:\n| a | b |\n|---|---|\n| 1 | 2 |\n", "Here:", 1),
])
def test_hold_open_table_holds_open_tables(text, body, rows):
    assert markup.hold_open_table(text) == (body, rows)


@pytest.mark.parametrize("text", [
    "Intro\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nAfter",           # closed by a blank line
    "```\n| a | b |\n|---|---|\n",                                # inside a code fence
    "plain text with a | pipe",
])
def test_hold_open_table_leaves_closed_or_non_tables(text):
    assert markup.hold_open_table(text) == (text, None)


# ---- exactly the two subscription windows ----

def test_only_the_two_subscription_windows_are_tracked():
    out = usage.normalize_account_usage({
        "five_hour": {"utilization": 87.0, "resets_at": None},
        "seven_day": {"utilization": 70.0, "resets_at": None},
        "seven_day_sonnet": {"utilization": 12.0, "resets_at": None},   # transitional, dropped
        "extra_usage": {"utilization": 3.0},
    })
    assert set(out) == {"five_hour", "seven_day"}
    assert usage.keep_window("seven_day") and not usage.keep_window("seven_day_opus")
    stale = {"five_hour": out["five_hour"], "seven_day_sonnet": out["seven_day"]}
    assert [k for k, _ in usage.ordered_windows(stale)] == ["five_hour"]
    assert "5h" in usage.footer_line(out) and "7d" in usage.footer_line(out)


def test_tidy_untitled_reads_every_page(monkeypatch):
    """A leftover beyond the 100 newest sessions must be seen."""
    sm = sessions.SessionManager(bot=SimpleNamespace(), settings=SimpleNamespace(),
                                 gate=SimpleNamespace())
    rows = [{"thread_id": -(i + 1), "name": f"Topic {i}", "name_auto": True} for i in range(150)]
    rows[140]["name"] = "Not named yet"
    calls = []

    async def _browse(uid, kw, limit=8, offset=0):
        calls.append(offset)
        return rows[offset:offset + limit], len(rows)

    async def _totals(ids):
        return {tid: {"requests": 1} for tid in ids}

    named = []

    async def _derive(key):
        return "u up?"

    async def _set_name(tid, name, *, manual=True):
        named.append(tid)

    monkeypatch.setattr(db, "browse_threads", _browse)
    monkeypatch.setattr(db, "get_usage_totals_bulk", _totals)
    monkeypatch.setattr(db, "set_session_name", _set_name)
    monkeypatch.setattr(sm, "_derive_session_name", _derive)
    assert asyncio.run(sm.tidy_untitled(7, keep=0)) == (1, 0)
    assert calls == [0, 100] and named == [-141]


# ---- model line in thinking indicator ----

def test_runs_as_label_names_the_resolved_model():
    assert models.runs_as_label("opus") == "opus"                 # no catalog: the value
    models.capture({"models": CATALOG})
    assert models.runs_as_label("default") == "Opus 5.5"          # not "Default (recommended)"
    assert models.runs_as_label("opus", "claude-opus-5-5[1m]") == "Opus 5.5"
    assert models.runs_as_label("claude-opus-4-8") == "📌 Opus 4.8"
    assert models.runs_as_label("mystery") == "mystery"


def test_model_line_names_what_the_turn_runs_on():
    models.capture({"models": CATALOG})
    sm = sessions.SessionManager(bot=SimpleNamespace(), settings=SimpleNamespace(
        default_model="opus"), gate=SimpleNamespace())
    rec = sm._record(-4)
    rec.model = "default"
    rec.session = SimpleNamespace(resolved_model="claude-opus-5-5", applied_effort="high")
    assert sm._model_line(rec, "en") == "Opus 5.5 · high"
    assert sm._model_line(rec, "ru") == "Opus 5.5 · " + i18n.CATALOG["effort.level.high"]["ru"]
    rec.session = SimpleNamespace(resolved_model=None, applied_effort=None)
    rec.model, rec.effort = "sonnet", None
    assert sm._model_line(rec, "en") == "Sonnet 5.5"              # default effort not known yet
    models.note_applied("sonnet", {"effort": "medium"}, None)
    assert sm._model_line(rec, "en") == "Sonnet 5.5 · medium"
    rec.model = "haiku"
    assert sm._model_line(rec, "en") == "Haiku 4.5"               # takes no effort level
    rec.model, rec.effort = "claude-opus-4-8", "max"
    assert sm._model_line(rec, "en") == "📌 Opus 4.8 · max"


def test_thinking_html_leads_with_the_model_line(monkeypatch):
    s = streamer.Streamer(_RichBot(), 1, None)
    assert s._thinking_html("💭 Thinking…") == "<tg-thinking>💭 Thinking…</tg-thinking>"
    s.model_line = "Opus 5.5 · high <x>"
    assert s._thinking_html("💭 Thinking…") == (
        "<tg-thinking>Opus 5.5 · high &lt;x&gt;<br>💭 Thinking…</tg-thinking>")
    monkeypatch.setattr(streamer, "_THINKING_MODEL_LINE", False)    # the rollback switch
    assert s._thinking_html("x") == "<tg-thinking>x</tg-thinking>"


def test_start_retries_a_draft_rejected_with_the_model_line():
    from aiogram.exceptions import TelegramBadRequest

    class _PickyBot(_RichBot):
        async def __call__(self, method):
            if "<br>" in method.rich_message["html"]:
                raise TelegramBadRequest(method=method, message="Bad Request: can't parse")
            self.methods.append(method)

    async def _t():
        s = streamer.Streamer(_PickyBot(), 5, None, use_drafts=True, controllable=False)
        s.model_line = "Opus 5.5 · high"
        await s.start()
        if s._anim_task is not None:
            s._anim_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await s._anim_task
        return s
    s = asyncio.run(_t())
    assert s.use_drafts and s.model_line == ""                    # drafts kept, line dropped
    assert len(s.bot.methods) == 1 and "<br>" not in s.bot.methods[0].rich_message["html"]


# ---- daily CLI update, graceful recycle ----

def _utc(*a):
    return datetime(*a, tzinfo=timezone.utc).timestamp()


def test_parse_and_format_update_time():
    assert sessions.parse_update_time("12:00") == (12, 0)
    assert sessions.parse_update_time("7") == (7, 0)
    assert sessions.parse_update_time(" 23:59 ") == (23, 59)
    for off in ("off", "", None, "never", "24:00", "12:60", "noon"):
        assert sessions.parse_update_time(off) is None
    assert sessions.format_update_time((9, 5)) == "09:05"
    assert sessions.format_update_time(None) == "off"


def test_update_is_due_once_a_day_and_catches_up():
    noon = (12, 0)
    assert sessions.last_update_slot(_utc(2026, 10, 4, 11, 59), noon) == _utc(2026, 10, 3, 12)
    assert sessions.last_update_slot(_utc(2026, 10, 4, 12, 0), noon) == _utc(2026, 10, 4, 12)
    sm = sessions.SessionManager(bot=SimpleNamespace(), settings=SimpleNamespace(
        cli_update_at="12:00"), gate=SimpleNamespace())
    assert sm.cli_update_at == noon
    sm.cli_last_check = _utc(2026, 10, 3, 23, 10)                 # yesterday, after its slot
    assert not sm.cli_update_due(_utc(2026, 10, 4, 11, 59))
    assert sm.cli_update_due(_utc(2026, 10, 4, 12, 1))            # today's slot has passed
    assert sm.cli_update_due(_utc(2026, 10, 6, 9, 0))             # missed while down: catch up
    sm.cli_last_check = _utc(2026, 10, 4, 12, 0, 30)
    assert not sm.cli_update_due(_utc(2026, 10, 4, 18, 0))        # already ran today
    asyncio.run(_set_off(sm))
    assert not sm.cli_update_due(_utc(2026, 10, 9, 12, 0))        # off


async def _set_off(sm):
    async def _noop(*a, **k):
        return None
    orig, db.set_kv = db.set_kv, _noop
    try:
        await sm.set_cli_update_at(None)
    finally:
        db.set_kv = orig


def test_cli_update_recycles_idle_clients_and_never_a_busy_one(monkeypatch):
    sm = sessions.SessionManager(bot=SimpleNamespace(), settings=SimpleNamespace(
        default_model="opus", sandbox_per_session_uid=True), gate=SimpleNamespace())
    closed: list[str] = []

    class _Client:
        def __init__(self, name):
            self.name = name

        async def aclose(self):
            closed.append(self.name)

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(db, "set_kv", _noop)
    monkeypatch.setattr(cli_update, "update_and_stage", lambda stage_jail: cli_update.UpdateResult(
        ok=True, before="2.1.289", after="2.1.290", staged=True, detail="updated"))

    async def _forever():
        await asyncio.sleep(3600)

    async def _t():
        idle, busy = sm._record(-1), sm._record(-2)
        idle.session, busy.session = _Client("idle"), _Client("busy")
        busy.worker = asyncio.ensure_future(_forever())
        res = await sm.update_cli_now()
        fresh = sm._record(-3)
        fresh.session = _Client("fresh")
        fresh.cli_generation = sm._cli_generation                 # built on the new binary
        during = list(closed)
        busy.worker.cancel()                                      # its reply is done
        with contextlib.suppress(asyncio.CancelledError):
            await busy.worker
        await sm._reap_once()
        return res, during
    res, during = asyncio.run(_t())
    assert res.changed and during == ["idle"]                     # the reply is never cut
    assert closed == ["idle", "busy"]                             # it moves once idle
    assert sm._records[-1].session is None and sm._records[-3].session is not None


# ---- the `/new` confirmation ----

def test_new_session_confirmation_is_the_glyph_and_model_line_only():
    for lang in ("en", "ru"):
        line = i18n.t("session.model_line", lang, model="Opus 5.5", effort="medium")
        assert line == "Opus 5.5 · medium"
        assert i18n.t("session.created", lang, glyph="💬", name="n", meta=line,
                      tagline="t") == "💬 Opus 5.5 · medium"


# ---- probe catalog beats a sandboxed session's view ----

# A sandboxed CLI reports family names, versions only in prose.
REDUCED = [
    {"value": "default", "resolvedModel": "claude-opus-5-5", "displayName": "Default (recommended)",
     "description": "Opus 5.5 · Best for everyday, complex tasks"},
    {"value": "opus", "resolvedModel": "claude-opus-5-5", "displayName": "Opus"},
    {"value": "haiku", "resolvedModel": "claude-haiku-4-5-20251001", "displayName": "Haiku"},
]


def test_session_capture_never_replaces_the_probe_catalog():
    assert models.capture({"models": REDUCED}) is True            # fills in before any probe
    assert models.capture({"models": CATALOG}, authoritative=True) is True
    assert models.capture({"models": REDUCED}) is False           # a session's view is ignored
    assert models.label("opus") == "Opus 5.5" and models.is_selectable("claude-opus-4-8")
    assert models.capture({"models": CATALOG[:2]}, authoritative=True) is True  # probe refreshes


def test_probe_authority_survives_a_restart(monkeypatch):
    store: dict = {}

    async def _get(key, default=None):
        return store.get(key, default)

    async def _set(key, value):
        store[key] = value

    monkeypatch.setattr(db, "get_kv", _get)
    monkeypatch.setattr(db, "set_kv", _set)
    models.capture({"models": CATALOG}, authoritative=True)
    asyncio.run(models.flush())
    monkeypatch.setattr(models, "_catalog", [])
    monkeypatch.setattr(models, "_authoritative", False)
    asyncio.run(models.load())
    assert models.capture({"models": REDUCED}) is False


def test_family_only_names_get_the_version_from_the_resolved_id():
    models.capture({"models": REDUCED})
    assert models.label("opus") == "Opus 5.5"
    assert models.label("haiku") == "Haiku 4.5"                   # the date suffix is dropped
    assert models.label("default") == "Default (recommended)"     # not a family name: as is
    assert models.runs_as_label("default") == "Opus 5.5"


# ---- thinking-phase draft-release cycle ----

class _ReleaseBot:
    def __init__(self):
        self.sent, self.deleted, self.drafts = [], [], []

    async def __call__(self, method):
        self.drafts.append(method)

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)
        return SimpleNamespace(message_id=100 + len(self.sent))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)
        return True


def _releasing_streamer(bot, period):
    s = streamer.Streamer(bot, 5, None, use_drafts=True, controllable=False)
    s.draft_release_secs = period
    s._streaming = True
    s._start_time = time.monotonic() - 20
    return s


def test_release_cycle_runs_only_while_the_thinking_tag_shows(monkeypatch):
    monkeypatch.setattr(streamer, "_DRAFT_RELEASE_HOLD_SECS", 0)
    bot = _ReleaseBot()
    s = _releasing_streamer(bot, 15)
    asyncio.run(s._render_draft())
    assert len(bot.sent) == 1 and bot.deleted == [101]            # landed, then deleted
    assert "<tg-thinking>" in bot.drafts[-1].rich_message["html"]  # indicator put back
    asyncio.run(s._render_draft())
    assert len(bot.sent) == 1                                     # not again within the period
    s._last_release -= 30
    s._full = "The answer starts"
    s._shown = len(s._full)
    asyncio.run(s._render_draft())
    assert len(bot.sent) == 1                                     # never while text streams


def test_release_cycle_is_off_without_a_period():
    bot = _ReleaseBot()
    asyncio.run(_releasing_streamer(bot, 0)._render_draft())
    assert bot.sent == [] and bot.drafts                          # just the indicator


def test_release_placeholder_is_cleaned_up():
    bot = _ReleaseBot()
    s = _releasing_streamer(bot, 15)
    s._release_msg_id = 42
    asyncio.run(s._drop_release_msg())
    asyncio.run(s._drop_release_msg())                            # idempotent
    assert bot.deleted == [42]


def test_release_period_scope(monkeypatch):
    monkeypatch.setattr(streamer, "_DRAFT_RELEASE_SECS", 15.0)
    monkeypatch.setattr(streamer, "_DRAFT_RELEASE_SCOPE", "owner")
    assert streamer.draft_release_period(5, 5) == 15.0
    assert streamer.draft_release_period(6, 5) == 0.0             # owner only while testing
    monkeypatch.setattr(streamer, "_DRAFT_RELEASE_SCOPE", "all")
    assert streamer.draft_release_period(6, 5) == 15.0
    monkeypatch.setattr(streamer, "_DRAFT_RELEASE_SCOPE", "off")
    assert streamer.draft_release_period(5, 5) == 0.0


# ---- the draft push button ----

def test_push_button_rides_on_the_drafts():
    bot = _ReleaseBot()
    s = _releasing_streamer(bot, 0)
    s.push_button = True
    asyncio.run(s._render_draft())
    assert bot.drafts[-1].can_stop is True
    s.push_button = False
    s._rendered_text = ""
    asyncio.run(s._render_draft())
    assert bot.drafts[-1].can_stop is None


def test_push_moves_the_reply_to_a_new_draft():
    s = _releasing_streamer(_ReleaseBot(), 0)
    s._rendered_text = "frame"
    old = s._draft_id
    assert s.on_push(old + 12345) is False                       # some other draft
    assert s.on_push(old) is True
    assert s._draft_id != old and s._rendered_text == ""         # next frame re-sends it


def test_session_routes_a_push_to_the_live_draft():
    sm = sessions.SessionManager(bot=SimpleNamespace(), settings=SimpleNamespace(
        default_model="opus"), gate=SimpleNamespace())
    rec = sm._record(-7)
    rec.streamer = _releasing_streamer(_ReleaseBot(), 0)
    draft = rec.streamer._draft_id
    assert sm.on_generation_stopped(6, draft) is False           # another chat
    assert sm.on_generation_stopped(5, draft) is True
    assert rec.streamer._draft_id != draft


def test_stopped_generation_is_read_from_the_raw_update():
    from aiogram.types import Update
    from app.telegram import rich_message
    push = Update.model_validate({"update_id": 1, "stopped_message_generation": {
        "chat": {"id": 5, "type": "private"}, "draft_id": 77}})
    assert rich_message.stopped_generation_of(push) == (5, 77)
    msg = Update.model_validate({"update_id": 2, "message": {
        "message_id": 1, "date": 0, "chat": {"id": 5, "type": "private"}, "text": "hi"}})
    assert rich_message.stopped_generation_of(msg) is None


def test_push_scope_and_release_withdrawn(monkeypatch):
    if "DRAFT_RELEASE" not in os.environ:
        assert streamer.draft_release_period(5, 5) == 0.0        # off by default
    if "DRAFT_PUSH" not in os.environ:
        assert streamer.draft_push_enabled(6, 5)                 # released to every user
    monkeypatch.setattr(streamer, "_DRAFT_PUSH_SCOPE", "owner")
    assert streamer.draft_push_enabled(5, 5) and not streamer.draft_push_enabled(6, 5)
    monkeypatch.setattr(streamer, "_DRAFT_PUSH_SCOPE", "all")
    assert streamer.draft_push_enabled(6, 5)
    monkeypatch.setattr(streamer, "_DRAFT_PUSH_SCOPE", "off")
    assert not streamer.draft_push_enabled(5, 5)


# ---- a press with no held message means stop ----

def test_push_without_a_message_stops_the_reply(monkeypatch):
    monkeypatch.setattr(sessions, "_PUSH_STOP_WAIT_SECS", 0)
    sm = sessions.SessionManager(bot=SimpleNamespace(), settings=SimpleNamespace(
        default_model="opus"), gate=SimpleNamespace())
    stopped: list[int] = []

    async def _stop(tid):
        stopped.append(tid)
        return True

    monkeypatch.setattr(sm, "stop", _stop)

    async def _forever():
        await asyncio.sleep(3600)

    async def _press(message_follows):
        rec = sm._record(-7)
        rec.streamer = _releasing_streamer(_ReleaseBot(), 0)
        rec.worker = asyncio.ensure_future(_forever())
        try:
            assert sm.on_generation_stopped(5, rec.streamer._draft_id)
            if message_follows:                                   # the held message arrives
                sm._inbound_by_chat[5] = sm._inbound_by_chat.get(5, 0) + 1
            await asyncio.gather(*list(sm._push_tasks))
        finally:
            rec.worker.cancel()

    asyncio.run(_press(True))
    assert stopped == []                                          # a push: nothing stopped
    asyncio.run(_press(False))
    assert stopped == [-7]                                        # nothing came: it was a stop
