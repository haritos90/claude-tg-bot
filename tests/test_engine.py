"""Tests for global-memory INJECTION + the isolation invariant (#130).

The fix: GLOBAL MEMORY injects the owner's ``~/.claude/CLAUDE.md`` (+ memory) CONTENT
directly into the system prompt and NEVER widens ``setting_sources`` to ``["user"]``
(which would also load ``settings.json`` permissions/env). So the invariant
``setting_sources == []`` must hold in BOTH states, and the memory text must reach
the model only when global memory is on.
"""

import os

import engine


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


def test_no_memory_file_means_no_injection(monkeypatch, tmp_path):
    """On but no ~/.claude/CLAUDE.md → nothing to inject; chat prompt is the plain one."""
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)  # dir exists, no CLAUDE.md
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(tmp_path), 1))
    s = _sess("chat", global_memory=True)
    assert s._global_memory_block() == ""
    opts = s._build_options()
    assert opts.setting_sources == []
    # #243: the table-format note is always appended; with no memory file nothing else is.
    assert opts.system_prompt == engine.CHAT_SYSTEM_PROMPT + engine.TABLE_FORMAT_NOTE


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
