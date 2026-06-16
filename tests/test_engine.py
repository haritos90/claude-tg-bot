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
    assert opts.system_prompt == engine.CHAT_SYSTEM_PROMPT
