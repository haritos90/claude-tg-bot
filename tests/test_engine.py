"""Tests for global-memory INJECTION + the isolation invariant (#130).

The fix: GLOBAL MEMORY injects the owner's ``~/.claude/CLAUDE.md`` (+ memory) CONTENT
directly into the system prompt and NEVER widens ``setting_sources`` to ``["user"]``
(which would also load ``settings.json`` permissions/env). So the invariant
``setting_sources == []`` must hold in BOTH states, and the memory text must reach
the model only when global memory is on.
"""

import asyncio
import os

from app.core import engine


def _redirect_home(monkeypatch, tmp_path, memo="REMEMBER: always be terse"):
    """Point ~ at a temp home holding ~/.claude/CLAUDE.md = memo."""
    claude = tmp_path / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    (claude / "CLAUDE.md").write_text(memo, encoding="utf-8")
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(tmp_path), 1))
    return memo


def _sess(mode, **kw):
    return engine.ClaudeSession(mode=mode, model="claude-opus-4-8", cwd="/tmp", **kw)


def test_isolation_kept_when_global_memory_off(monkeypatch, tmp_path):
    """Off → setting_sources=[] and the memo never reaches the prompt, even if present."""
    memo = _redirect_home(monkeypatch, tmp_path)
    s = _sess("chat", global_memory=False)
    assert s._global_memory_block() == ""
    opts = s._build_options()
    assert opts.setting_sources == []
    assert memo not in (opts.system_prompt or "")


def test_global_memory_injected_without_widening_setting_sources(monkeypatch, tmp_path):
    """On → setting_sources STAYS [] (never "user"); the memo is injected directly:
    chat appends to the system-prompt string, code appends to the claude_code preset."""
    memo = _redirect_home(monkeypatch, tmp_path)

    s = _sess("chat", global_memory=True)
    opts = s._build_options()
    assert opts.setting_sources == []          # #130: NEVER ["user"]
    assert memo in opts.system_prompt          # injected directly

    sc = _sess("code", global_memory=True)
    optsc = sc._build_options()
    assert optsc.setting_sources == []
    sp = optsc.system_prompt
    assert isinstance(sp, dict) and sp.get("preset") == "claude_code"
    assert memo in sp.get("append", "")


def test_bot_context_note_injected_in_both_modes():
    """#265: the agent is told it's a Telegram bot (modes, /code, /shell) in chat AND code."""
    chat = _sess("chat")._build_options()
    assert engine.BOT_CONTEXT_NOTE in (chat.system_prompt or "")
    assert "/shell" in chat.system_prompt and "Telegram bot" in chat.system_prompt
    code = _sess("code")._build_options()
    append = code.system_prompt.get("append", "")
    assert engine.BOT_CONTEXT_NOTE in append
    # #269: outbox + isolation + table notes are consolidated into the one doc.
    assert "outbox/" in append and "private" in append.lower() and "20 columns" in append


def test_session_state_note_mode_and_level_aware():
    """#276: the dynamic note tells the model the current mode + what the user can do.
    chat + chat-only level → 'cannot upgrade' (no /code); chat + code level → offer /code;
    code session → mention /shell + /chat."""
    chat_only = engine.ClaudeSession(mode="chat", model="claude-opus-4-8", cwd="/tmp",
                                     user_level="chat")._session_state_note()
    assert "chat-only" in chat_only.lower() and "owner" in chat_only.lower()
    assert "/code" in chat_only  # mentioned (as the thing they CAN'T self-do)

    chat_code = engine.ClaudeSession(mode="chat", model="claude-opus-4-8", cwd="/tmp",
                                     user_level="code")._session_state_note()
    assert "/code" in chat_code and "/chat" in chat_code
    assert "chat-only" not in chat_code.lower()

    code = engine.ClaudeSession(mode="code", model="claude-opus-4-8", cwd="/tmp",
                                user_level="code")._session_state_note()
    assert "/shell" in code and "/chat" in code


def test_no_memory_file_means_no_injection(monkeypatch, tmp_path):
    """On but no ~/.claude/CLAUDE.md → nothing to inject; chat prompt is the plain one."""
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)  # dir exists, no CLAUDE.md
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(tmp_path), 1))
    s = _sess("chat", global_memory=True)
    assert s._global_memory_block() == ""
    opts = s._build_options()
    assert opts.setting_sources == []
    # #265/#269: the bot-context doc is always appended; with no memory file nothing else is.
    # #276: a dynamic "this session right now" note is also appended (mode + level aware).
    assert opts.system_prompt == (engine.CHAT_SYSTEM_PROMPT + engine.BOT_CONTEXT_NOTE
                                  + s._session_state_note())


# ----------------------------------------------------------- session memory (#352)

def test_apply_session_note_append_replace_and_cap():
    """The pure note policy: append by default, replace on demand, ignore an empty note,
    and trim the OLDEST whole lines so the blob never exceeds the cap."""
    assert engine._apply_session_note("", "hello", False) == "hello"
    assert engine._apply_session_note("a", "b", False) == "a\nb"          # append
    assert engine._apply_session_note("a\nb", "c", True) == "c"           # replace whole set
    assert engine._apply_session_note("a\nb", "   ", False) == "a\nb"     # empty note = no-op
    # Over-cap append keeps the most recent content, cut on a line boundary, under cap.
    big = "\n".join(f"line{i}" for i in range(5000))
    out = engine._apply_session_note(big, "newest", False, cap=100)
    assert len(out) <= 100
    assert out.endswith("newest") and "\n" in out
    # The partial leading line was dropped: `out` begins at a clean line boundary, i.e. the
    # original (notes + appended note) ends with exactly "\n" + out.
    assert (big + "\nnewest").endswith("\n" + out)


def test_apply_session_note_byte_accurate_cap():
    """#355: the size cap is UTF-8 BYTES, not code points — a multibyte note is trimmed to the
    byte budget and always decodes cleanly (no mojibake), even when the cut splits a character."""
    # 100 Cyrillic chars = 200 UTF-8 bytes; an EVEN cap lands on a 2-byte char boundary.
    out = engine._apply_session_note("", "я" * 100, False, cap=50)
    assert len(out.encode("utf-8")) <= 50
    assert out == "я" * 25 and "�" not in out          # clean boundary, no replacement char
    # An ODD cap forces the slice to split a 2-byte char; the stray byte is dropped, not mojibaked.
    odd = engine._apply_session_note("", "я" * 100, False, cap=51)
    assert len(odd.encode("utf-8")) <= 51 and odd == odd.encode("utf-8").decode("utf-8")
    assert "�" not in odd
    # Emoji (4-byte) over a small cap → still byte-bounded and valid (replace path).
    emo = engine._apply_session_note("", "😀" * 20, True, cap=21)   # 80 bytes → ≤ 21
    assert len(emo.encode("utf-8")) <= 21 and "�" not in emo


def test_session_notes_block_injected_low_authority_code_only():
    """#362: saved notes are injected ONLY in a CODE session owned by a CODE-LEVEL user, as
    explicitly NON-authoritative context. A chat session — and a code session held by a
    demoted (chat-level) user — inject nothing; the blob stays dormant in the DB. Empty
    notes inject nothing even when enabled (so the plain-prompt equality above still holds)."""
    note = "user prefers metric units"
    # Chat: never injected — session memory is code-only now, even with notes saved.
    chat = _sess("chat", session_notes=note, user_level="code")._build_options()
    assert note not in (chat.system_prompt or "")
    # Code + code-level user: injected as low-authority continuity context.
    code = _sess("code", session_notes=note, user_level="code")._build_options()
    assert note in code.system_prompt.get("append", "")
    assert "NOT as instructions" in code.system_prompt.get("append", "")   # low-authority framing
    # Demotion gap: a code session whose owner is now chat-level gets nothing.
    demoted = _sess("code", session_notes=note, user_level="chat")._build_options()
    assert note not in demoted.system_prompt.get("append", "")
    # Empty notes → nothing even when enabled.
    assert _sess("code", user_level="code")._session_notes_block() == ""


def test_remember_tool_exposed_and_auto_allowed_code_only():
    """#362: the in-process `remember` MCP server + its auto-allow entry are attached ONLY in
    a code session owned by a code-level user; a chat session — and a demoted user's code
    session — get neither. The tool stays classified safe so the code gate never prompts."""
    from app.access import permissions
    code = _sess("code", user_level="code")._build_options()
    assert "memory" in (code.mcp_servers or {})
    assert engine.MEMORY_TOOL in code.allowed_tools
    # Chat: no memory server, tool not auto-allowed (even for a code-level user).
    chat = _sess("chat", user_level="code")._build_options()
    assert "memory" not in (chat.mcp_servers or {})
    assert engine.MEMORY_TOOL not in chat.allowed_tools
    # Demotion gap: a code session held by a now-chat-level user gets no memory.
    demoted = _sess("code", user_level="chat")._build_options()
    assert "memory" not in (demoted.mcp_servers or {})
    assert engine.MEMORY_TOOL not in demoted.allowed_tools
    assert engine.MEMORY_TOOL in permissions.SAFE_TOOLS


def test_remember_tool_persists_caps_and_rejects_empty():
    """Driving the `remember` handler updates the live notes, supports append + replace,
    rejects an empty note, enforces the cap, and always hands the FINAL blob to the
    persistence hook."""
    saved: list[str] = []

    async def _persist(blob):
        saved.append(blob)

    s = engine.ClaudeSession(mode="chat", model="claude-opus-4-8", cwd="/tmp",
                             on_remember=_persist)

    async def _run():
        r = await s._remember_tool({"note": "first fact"})
        assert "Saved" in r["content"][0]["text"]
        assert s.session_notes == "first fact"
        await s._remember_tool({"note": "second fact"})
        assert s.session_notes == "first fact\nsecond fact"
        await s._remember_tool({"note": "consolidated", "replace": True})
        assert s.session_notes == "consolidated"
        bad = await s._remember_tool({"note": "   "})
        assert bad.get("is_error") and s.session_notes == "consolidated"  # unchanged
        big = await s._remember_tool(
            {"note": "y" * (engine.SESSION_NOTES_CAP + 1000), "replace": True})
        assert "trimmed" in big["content"][0]["text"]

    asyncio.run(_run())
    assert len(s.session_notes) <= engine.SESSION_NOTES_CAP
    assert saved[-1] == s.session_notes                                  # hook got the final blob


# ----------------------------------------------------------- big_memory 1M (#134)

def test_one_m_model_appends_suffix_for_capable_models_only():
    """[1m] is appended only to 1M-capable models (Opus by default), never doubled."""
    assert engine._one_m_model("claude-opus-4-8") == "claude-opus-4-8[1m]"
    assert engine._one_m_model("opus") == "opus[1m]"                 # alias form too
    assert engine._one_m_model("claude-sonnet-4-6") == "claude-sonnet-4-6"   # paid → off
    assert engine._one_m_model("claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"
    assert engine._one_m_model("claude-opus-4-8[1m]") == "claude-opus-4-8[1m]"  # no double
    assert engine._one_m_model("") == ""


def test_big_memory_requests_1m_via_model_suffix():
    """big_memory ON appends [1m] to an Opus session's model (the real 1M request);
    OFF leaves it clean; a paid-gated model (Sonnet) stays unchanged even when ON; and
    the retired `betas` no-op is never passed."""
    on = _sess("chat", big_memory=True)._build_options()
    assert on.model == "claude-opus-4-8[1m]"
    assert not getattr(on, "betas", None)                  # retired no-op not passed

    off = _sess("chat", big_memory=False)._build_options()
    assert off.model == "claude-opus-4-8"

    son = engine.ClaudeSession(mode="code", model="claude-sonnet-4-6", cwd="/tmp",
                               big_memory=True)._build_options()
    assert son.model == "claude-sonnet-4-6"                 # paid-gated → no suffix


def test_big_memory_1m_models_env_override(monkeypatch):
    """A deployer who enabled usage-credits can widen the 1M set via BIG_MEMORY_1M_MODELS."""
    monkeypatch.setattr(engine, "_ONE_M_MODELS", ("opus", "sonnet"))
    son = engine.ClaudeSession(mode="chat", model="claude-sonnet-4-6", cwd="/tmp",
                               big_memory=True)._build_options()
    assert son.model == "claude-sonnet-4-6[1m]"


# ------------------------------------------------ #227a persistent-shell parsing

def test_persistent_shell_parse_strips_noise_and_extracts_rc():
    """#227a: _parse pulls the exit code from the sentinel and strips terminal noise
    (bracketed-paste escapes, carriage returns); output before the sentinel is clean."""
    import types
    sh = engine.PersistentShell(types.SimpleNamespace(returncode=None), -1)
    rc, out = sh._parse(b"\x1b[?2004l\r\nhello\n\x1b[?2004h__SBX_SH_DONE__:0\n")
    assert rc == 0 and out == "hello"
    rc, out = sh._parse(b"\x1b[?2004l\r\noops\n__SBX_SH_DONE__:7\n\x1b[?2004h")
    assert rc == 7 and out == "oops"
    # no sentinel (timeout/partial) → rc 0, cleaned text
    rc, out = sh._parse(b"\x1b[?2004lpartial output\r\n")
    assert rc == 0 and out == "partial output"


def test_latest_frame_collapses_alt_screen_redraws():
    """#246b: a full-redraw alt-screen TUI keeps only the latest frame; ordinary output
    (no alt-screen, even with a bare clear) is left untouched."""
    # Alt-screen picker: enter, draw frame 1, clear, draw frame 2 (current).
    raw = "\x1b[?1049h\x1b[H> Login with a web browser\n  Paste a token\x1b[2J\x1b[H> Paste a token\n  Login with a web browser"
    assert engine._latest_frame(raw).strip().startswith("> Paste a token")
    assert "Login with a web browser\n  Paste a token" not in engine._latest_frame(raw)
    # After exiting the alt screen, the final post-exit output wins.
    raw2 = "\x1b[?1049h\x1b[Hpicking…\x1b[?1049l\n✓ Logged in"
    assert "Logged in" in engine._latest_frame(raw2)
    assert "picking" not in engine._latest_frame(raw2)
    # No alt-screen → unchanged (a bare `clear` uses ESC[2J but not ?1049h).
    plain = "line one\n\x1b[2J\x1b[Hline two"
    assert engine._latest_frame(plain) == plain


def test_first_token_timeout_surfaces_service_unavailable(monkeypatch):
    """#343: a turn that produces NO first message within the watchdog window is cut short with a
    localized service-unavailable error (not an endless 'thinking…' hang), the client is dropped so
    the next turn rebuilds, and the resume context (session_id) is preserved — exactly one event."""
    import asyncio

    monkeypatch.setattr(engine, "_FIRST_TOKEN_TIMEOUT_SEC", 0.05)

    class _StallClient:
        def __init__(self):
            self.disconnected = False

        async def disconnect(self):
            self.disconnected = True

        async def receive_response(self):
            await asyncio.sleep(5)   # never yields a first message within the window
            yield object()           # pragma: no cover — unreachable in the test

    sess = engine.ClaudeSession("chat", "claude-opus-4-8", None, resume_session_id="resume-abc")
    stall = _StallClient()

    async def _ensure():
        sess.client = stall

    async def _send(*a, **k):
        return None

    monkeypatch.setattr(sess, "_ensure_client", _ensure)
    monkeypatch.setattr(sess, "_send_query", _send)

    async def _collect():
        out = []
        async for ev in sess.run("hello"):
            out.append(ev)
        return out

    events = asyncio.run(_collect())

    assert len(events) == 1                                     # one clean error, no double-reply
    assert events[0].kind == "error"
    assert events[0].error_key == "err.service_unavailable"
    assert sess.client is None and stall.disconnected          # client dropped → next turn rebuilds


def test_stall_after_reasoning_surfaces_service_unavailable(monkeypatch):
    """#358: a thinking_delta disarms the first-token watchdog (it is a StreamEvent), so a turn
    that streams REASONING and then goes silent — no answer text/tool/result — used to animate the
    <tg-thinking> draft forever. The stall watchdog now cuts it short with a service-unavailable
    error and drops the client. The first-token watchdog is set high so ONLY the stall guard fires."""
    import asyncio
    from claude_agent_sdk.types import StreamEvent

    monkeypatch.setattr(engine, "_FIRST_TOKEN_TIMEOUT_SEC", 5.0)   # not the guard under test
    monkeypatch.setattr(engine, "_STALL_TIMEOUT_SEC", 0.05)

    class _ReasonThenStallClient:
        def __init__(self):
            self.disconnected = False

        async def disconnect(self):
            self.disconnected = True

        async def receive_response(self):
            # reasoning arrives first → _progressed=True, _answered=False
            yield StreamEvent(uuid="u", session_id="resume-abc",
                              event={"type": "content_block_delta",
                                     "delta": {"thinking": "let me think…"}})
            await asyncio.sleep(5)   # then silence, far longer than the stall window
            yield object()           # pragma: no cover — unreachable in the test

    sess = engine.ClaudeSession("chat", "claude-opus-4-8", None, resume_session_id="resume-abc")
    client = _ReasonThenStallClient()

    async def _ensure():
        sess.client = client

    async def _send(*a, **k):
        return None

    monkeypatch.setattr(sess, "_ensure_client", _ensure)
    monkeypatch.setattr(sess, "_send_query", _send)

    async def _collect():
        out = []
        async for ev in sess.run("hello"):
            out.append(ev)
        return out

    events = asyncio.run(_collect())
    kinds = [e.kind for e in events]
    assert "thinking_delta" in kinds                            # the reasoning WAS surfaced
    assert events[-1].kind == "error"
    assert events[-1].error_key == "err.service_unavailable"
    assert sess.client is None and client.disconnected         # client dropped → next turn rebuilds


def test_reasoning_then_answer_does_not_false_timeout(monkeypatch):
    """#358: once REAL answer content starts the stall watchdog must disarm — a turn that streams a
    thinking_delta then answer text completes normally (text surfaced, no spurious error), even
    across a gap LONGER than the stall window (a long tool call / build legitimately emits nothing)."""
    import asyncio
    from claude_agent_sdk.types import StreamEvent

    monkeypatch.setattr(engine, "_FIRST_TOKEN_TIMEOUT_SEC", 5.0)
    monkeypatch.setattr(engine, "_STALL_TIMEOUT_SEC", 0.2)

    class _ReasonThenAnswerClient:
        async def disconnect(self):
            pass

        async def receive_response(self):
            yield StreamEvent(uuid="u", session_id="resume-abc",
                              event={"type": "content_block_delta",
                                     "delta": {"thinking": "thinking…"}})
            await asyncio.sleep(0)       # #368: yield only — near-instant, can't race the window
            yield StreamEvent(uuid="u", session_id="resume-abc",
                              event={"type": "content_block_delta",
                                     "delta": {"text": "the answer"}})
            await asyncio.sleep(0.4)     # > stall window, but _answered is set now → unbounded

    sess = engine.ClaudeSession("chat", "claude-opus-4-8", None, resume_session_id="resume-abc")
    client = _ReasonThenAnswerClient()

    async def _ensure():
        sess.client = client

    async def _send(*a, **k):
        return None

    monkeypatch.setattr(sess, "_ensure_client", _ensure)
    monkeypatch.setattr(sess, "_send_query", _send)

    async def _collect():
        out = []
        async for ev in sess.run("hi"):
            out.append(ev)
        return out

    events = asyncio.run(_collect())
    assert any(e.kind == "text_delta" and e.text == "the answer" for e in events)
    assert all(e.kind != "error" for e in events)              # no false stall timeout
    assert sess.session_id == "resume-abc"                      # resume context NOT nuked


def _run_with_error_message(monkeypatch, msg):
    """Drive one turn whose only streamed message is `msg` (an errored AssistantMessage)
    and return the emitted events."""
    class _OneMsgClient:
        async def disconnect(self):
            pass

        async def receive_response(self):
            yield msg

    sess = engine.ClaudeSession("chat", "claude-opus-4-8", None)
    client = _OneMsgClient()

    async def _ensure():
        sess.client = client

    async def _send(*a, **k):
        return None

    monkeypatch.setattr(sess, "_ensure_client", _ensure)
    monkeypatch.setattr(sess, "_send_query", _send)

    async def _collect():
        out = []
        async for ev in sess.run("hi"):
            out.append(ev)
        return out

    return asyncio.run(_collect())


def test_cyber_refusal_gets_distinct_key(monkeypatch):
    """#361: a cyber-safeguard refusal (invalid_request + stop_reason 'refusal', with a
    synthetic 'cybersecurity topic' explanation) is relabeled to err.cyber_refusal — NOT
    the misleading generic err.invalid_request."""
    from claude_agent_sdk.types import AssistantMessage, TextBlock

    msg = AssistantMessage(
        content=[TextBlock(text=(
            "API Error: Opus 4.8 (1M context) has safety measures that flagged this "
            "message for a cybersecurity topic. If your work requires this access, you "
            "can apply for an exemption. Try rephrasing in a new session."))],
        model="<synthetic>",
        error="invalid_request",
        stop_reason="refusal",
    )
    events = _run_with_error_message(monkeypatch, msg)
    err = [e for e in events if e.kind == "error"]
    assert len(err) == 1 and err[0].error_key == "err.cyber_refusal"
    assert err[0].error_detail == "invalid_request"        # raw type preserved for logs


def test_non_cyber_refusal_gets_generic_refusal_key(monkeypatch):
    """#361: a refusal whose explanation is NOT cyber falls back to err.model_refusal —
    still a distinct 'declined' message, never the 'invalid request' mislabel."""
    from claude_agent_sdk.types import AssistantMessage, TextBlock

    msg = AssistantMessage(
        content=[TextBlock(text="I can't help with that request.")],
        model="<synthetic>",
        error="invalid_request",
        stop_reason="refusal",
    )
    events = _run_with_error_message(monkeypatch, msg)
    err = [e for e in events if e.kind == "error"]
    assert len(err) == 1 and err[0].error_key == "err.model_refusal"


def test_real_invalid_request_still_generic(monkeypatch):
    """#361 regression: a genuine invalid_request (no refusal stop_reason) keeps the
    existing err.invalid_request mapping — the refusal relabel is refusal-only."""
    from claude_agent_sdk.types import AssistantMessage

    msg = AssistantMessage(
        content=[],
        model="claude-opus-4-8",
        error="invalid_request",
        stop_reason="end_turn",
    )
    events = _run_with_error_message(monkeypatch, msg)
    err = [e for e in events if e.kind == "error"]
    assert len(err) == 1 and err[0].error_key == "err.invalid_request"
