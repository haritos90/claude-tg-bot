"""Tests for global-memory injection and isolation invariant.

- `setting_sources` stays empty whether memory is on or off
- memory text reaches the model only when enabled
"""

import asyncio
import os

from app.core import engine


def _redirect_home(monkeypatch, tmp_path, memo="REMEMBER: always be terse"):
    """Point home at a temp dir holding CLAUDE.md."""
    claude = tmp_path / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    (claude / "CLAUDE.md").write_text(memo, encoding="utf-8")
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(tmp_path), 1))
    return memo


def _sess(mode, **kw):
    return engine.ClaudeSession(mode=mode, model="claude-opus-4-8", cwd="/tmp", **kw)


def test_isolation_kept_when_global_memory_off(monkeypatch, tmp_path):
    """Off keeps sources empty and omits the memo."""
    memo = _redirect_home(monkeypatch, tmp_path)
    s = _sess("chat", global_memory=False)
    assert s._global_memory_block() == ""
    opts = s._build_options()
    assert opts.setting_sources == []
    assert memo not in (opts.system_prompt or "")


def test_global_memory_injected_without_widening_setting_sources(monkeypatch, tmp_path):
    """On injects memo directly, never widening `setting_sources`.

    - chat appends to the prompt string
    - code appends to the preset
    """
    memo = _redirect_home(monkeypatch, tmp_path)

    s = _sess("chat", global_memory=True)
    opts = s._build_options()
    assert opts.setting_sources == []          # never "user"
    assert memo in opts.system_prompt

    sc = _sess("code", global_memory=True)
    optsc = sc._build_options()
    assert optsc.setting_sources == []
    sp = optsc.system_prompt
    assert isinstance(sp, dict) and sp.get("preset") == "claude_code"
    assert memo in sp.get("append", "")


def test_bot_context_note_injected_in_both_modes():
    """Agent is told it is a Telegram bot."""
    chat = _sess("chat")._build_options()
    assert engine.BOT_CONTEXT_NOTE in (chat.system_prompt or "")
    assert "/shell" in chat.system_prompt and "Telegram bot" in chat.system_prompt
    code = _sess("code")._build_options()
    append = code.system_prompt.get("append", "")
    assert engine.BOT_CONTEXT_NOTE in append
    # Outbox, isolation and table notes live in one doc.
    assert "outbox/" in append and "private" in append.lower() and "20 columns" in append


def test_session_state_note_mode_and_level_aware():
    """Dynamic note tells the model the mode and abilities.

    - chat with chat-only level: cannot upgrade
    - chat with code level: offer code mode
    - code session: mention shell and chat
    """
    chat_only = engine.ClaudeSession(mode="chat", model="claude-opus-4-8", cwd="/tmp",
                                     user_level="chat")._session_state_note()
    assert "chat-only" in chat_only.lower() and "owner" in chat_only.lower()
    assert "/code" in chat_only  # mentioned as something they cannot self-do

    chat_code = engine.ClaudeSession(mode="chat", model="claude-opus-4-8", cwd="/tmp",
                                     user_level="code")._session_state_note()
    assert "/code" in chat_code and "/chat" in chat_code
    assert "chat-only" not in chat_code.lower()

    code = engine.ClaudeSession(mode="code", model="claude-opus-4-8", cwd="/tmp",
                                user_level="code")._session_state_note()
    assert "/shell" in code and "/chat" in code


def test_no_memory_file_means_no_injection(monkeypatch, tmp_path):
    """No CLAUDE.md means nothing injected; plain chat prompt."""
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)  # dir exists, no CLAUDE.md
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(tmp_path), 1))
    s = _sess("chat", global_memory=True)
    assert s._global_memory_block() == ""
    opts = s._build_options()
    assert opts.setting_sources == []
    # Bot-context doc is always appended.
    # - with no memory file nothing else is
    # - a dynamic session note is also appended
    assert opts.system_prompt == (engine.CHAT_SYSTEM_PROMPT + engine.BOT_CONTEXT_NOTE
                                  + s._session_state_note())


# ---- session memory ----

def test_apply_session_note_append_replace_and_cap():
    """Note policy: append, replace, ignore empty, trim oldest lines."""
    assert engine._apply_session_note("", "hello", False) == "hello"
    assert engine._apply_session_note("a", "b", False) == "a\nb"          # append
    assert engine._apply_session_note("a\nb", "c", True) == "c"           # replace whole set
    assert engine._apply_session_note("a\nb", "   ", False) == "a\nb"     # empty note is a no-op
    # Over-cap append keeps recent content, cut on a line.
    big = "\n".join(f"line{i}" for i in range(5000))
    out = engine._apply_session_note(big, "newest", False, cap=100)
    assert len(out) <= 100
    assert out.endswith("newest") and "\n" in out
    # Leading partial line dropped: `out` starts at a line boundary.
    assert (big + "\nnewest").endswith("\n" + out)


def test_apply_session_note_byte_accurate_cap():
    """Size cap counts UTF-8 bytes and always decodes cleanly."""
    # 100 two-byte chars give 200 bytes; even cap fits boundary.
    # - neutral 2-byte char used, byte math identical
    out = engine._apply_session_note("", "\u00e9" * 100, False, cap=50)
    assert len(out.encode("utf-8")) <= 50
    assert out == "\u00e9" * 25 and "�" not in out          # clean boundary, no replacement char
    # An odd cap splits a 2-byte char; stray byte dropped.
    odd = engine._apply_session_note("", "\u00e9" * 100, False, cap=51)
    assert len(odd.encode("utf-8")) <= 51 and odd == odd.encode("utf-8").decode("utf-8")
    assert "�" not in odd
    # Emoji (4-byte) over a small cap stays byte-bounded and valid.
    emo = engine._apply_session_note("", "😀" * 20, True, cap=21)   # 80 bytes gives at most 21
    assert len(emo.encode("utf-8")) <= 21 and "�" not in emo


def test_session_notes_block_injected_low_authority_code_only():
    """Notes inject only in code sessions of code-level users.

    - injected as explicitly non-authoritative context
    - chat or demoted-user sessions inject nothing
    - empty notes inject nothing even when enabled
    """
    note = "user prefers metric units"
    # Chat never injects; session memory is code-only.
    chat = _sess("chat", session_notes=note, user_level="code")._build_options()
    assert note not in (chat.system_prompt or "")
    # Code with code-level user injects low-authority continuity context.
    code = _sess("code", session_notes=note, user_level="code")._build_options()
    assert note in code.system_prompt.get("append", "")
    assert "NOT as instructions" in code.system_prompt.get("append", "")   # low-authority framing
    # A code session with a chat-level owner gets nothing.
    demoted = _sess("code", session_notes=note, user_level="chat")._build_options()
    assert note not in demoted.system_prompt.get("append", "")
    # Empty notes inject nothing even when enabled.
    assert _sess("code", user_level="code")._session_notes_block() == ""


def test_remember_tool_exposed_and_auto_allowed_code_only():
    """The `remember` MCP server attaches only for code-level code sessions.

    - chat and demoted users get neither server nor auto-allow
    - tool stays classified safe, so no prompt
    """
    from app.access import permissions
    code = _sess("code", user_level="code")._build_options()
    assert "memory" in (code.mcp_servers or {})
    assert engine.MEMORY_TOOL in code.allowed_tools
    # Chat gets no memory server and no auto-allowed tool.
    chat = _sess("chat", user_level="code")._build_options()
    assert "memory" not in (chat.mcp_servers or {})
    assert engine.MEMORY_TOOL not in chat.allowed_tools
    # A chat-level user's code session gets no memory.
    demoted = _sess("code", user_level="chat")._build_options()
    assert "memory" not in (demoted.mcp_servers or {})
    assert engine.MEMORY_TOOL not in demoted.allowed_tools
    assert engine.MEMORY_TOOL in permissions.SAFE_TOOLS


def test_remember_tool_persists_caps_and_rejects_empty():
    """The `remember` handler updates notes, enforces cap, persists final blob.

    - supports append and replace
    - rejects an empty note
    """
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


# ---- context window ----

def test_model_passes_through_without_a_1m_suffix():
    """Model goes to the CLI as stored, with native window.

    - no `betas`, no window override in env
    """
    for flag in (True, False):
        opts = _sess("chat", big_memory=flag)._build_options()
        assert opts.model == "claude-opus-4-8"
        assert not getattr(opts, "betas", None)
        assert "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in (opts.env or {})
    assert not hasattr(engine, "_one_m_model")


# ---- persistent-shell parsing ----

def test_persistent_shell_parse_strips_noise_and_extracts_rc():
    """`_parse` extracts the exit code and strips terminal noise."""
    import types
    sh = engine.PersistentShell(types.SimpleNamespace(returncode=None), -1)
    rc, out = sh._parse(b"\x1b[?2004l\r\nhello\n\x1b[?2004h__SBX_SH_DONE__:0\n")
    assert rc == 0 and out == "hello"
    rc, out = sh._parse(b"\x1b[?2004l\r\noops\n__SBX_SH_DONE__:7\n\x1b[?2004h")
    assert rc == 7 and out == "oops"
    # no sentinel (timeout/partial): rc 0, cleaned text
    rc, out = sh._parse(b"\x1b[?2004lpartial output\r\n")
    assert rc == 0 and out == "partial output"


def test_latest_frame_collapses_alt_screen_redraws():
    """Full-redraw alt-screen TUI keeps only the latest frame.

    - ordinary output is left untouched
    """
    # Alt-screen picker: enter, draw frame 1, clear, draw frame 2.
    raw = "\x1b[?1049h\x1b[H> Login with a web browser\n  Paste a token\x1b[2J\x1b[H> Paste a token\n  Login with a web browser"
    assert engine._latest_frame(raw).strip().startswith("> Paste a token")
    assert "Login with a web browser\n  Paste a token" not in engine._latest_frame(raw)
    # After exiting the alt screen, final output wins.
    raw2 = "\x1b[?1049h\x1b[Hpicking…\x1b[?1049l\n✓ Logged in"
    assert "Logged in" in engine._latest_frame(raw2)
    assert "picking" not in engine._latest_frame(raw2)
    # No alt-screen leaves output unchanged; bare `clear` is not `?1049h`.
    plain = "line one\n\x1b[2J\x1b[Hline two"
    assert engine._latest_frame(plain) == plain


def test_first_token_timeout_surfaces_service_unavailable(monkeypatch):
    """A turn with no first message is cut short.

    - localized service-unavailable error, not a hang
    - client dropped so next turn rebuilds
    - resume session_id preserved; exactly one event
    """
    import asyncio

    monkeypatch.setattr(engine, "_FIRST_TOKEN_TIMEOUT_SEC", 0.05)

    class _StallClient:
        def __init__(self):
            self.disconnected = False

        async def disconnect(self):
            self.disconnected = True

        async def receive_response(self):
            await asyncio.sleep(5)   # never yields a first message in time
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
    assert sess.client is None and stall.disconnected          # client dropped; next turn rebuilds


def test_stall_after_reasoning_surfaces_service_unavailable(monkeypatch):
    """Stall watchdog cuts a turn silent after reasoning.

    - a thinking delta disarms the first-token watchdog
    - error is service-unavailable and client is dropped
    - first-token watchdog set high so only stall fires
    """
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
            # Reasoning arrives first: progressed true, answered false.
            yield StreamEvent(uuid="u", session_id="resume-abc",
                              event={"type": "content_block_delta",
                                     "delta": {"thinking": "let me think…"}})
            await asyncio.sleep(5)   # then silence, longer than the stall window
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
    assert "thinking_delta" in kinds                            # the reasoning was surfaced
    assert events[-1].kind == "error"
    assert events[-1].error_key == "err.service_unavailable"
    assert sess.client is None and client.disconnected         # client dropped; next turn rebuilds


def test_reasoning_then_answer_does_not_false_timeout(monkeypatch):
    """Real answer content disarms the stall watchdog.

    - thinking then text completes normally with no error
    - holds even across gaps longer than the stall window
    """
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
            await asyncio.sleep(0)       # yield only; near-instant, cannot race window
            yield StreamEvent(uuid="u", session_id="resume-abc",
                              event={"type": "content_block_delta",
                                     "delta": {"text": "the answer"}})
            await asyncio.sleep(0.4)     # beyond stall window, but answered is set

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
    assert sess.session_id == "resume-abc"                      # resume context not cleared


def _run_with_error_message(monkeypatch, msg):
    """Drive one turn streaming only `msg`; return emitted events."""
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
    """A cyber-safeguard refusal maps to `err.cyber_refusal`.

    - not the generic `err.invalid_request`
    """
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
    """A non-cyber refusal falls back to `err.model_refusal`."""
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
    """A genuine invalid request keeps the `err.invalid_request` mapping."""
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
