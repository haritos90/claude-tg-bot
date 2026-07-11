---
id: TASK-352
title: "Agent-driven per-topic \"session memory\" (chat + code) via an in-process `remember` tool"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 352
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In a long or complex chat the assistant can now remember key facts, decisions, or your preferences on its own — kept for that topic and surviving the conversation getting long, with no command needed. Use /forget to clear a topic's saved memory; /memory shows how much it has saved.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Chat is tool-free (no `./CLAUDE.md`, #314), so the agent had no way to keep durable notes across a long/complex session. Added an in-process SDK MCP tool `remember` the model calls ITSELF to append (or, with `replace=true`, rewrite) short notes for its OWN topic — the tool-free-chat equivalent of editing a project memory. It is served over the SDK stdio CONTROL channel (`_handle_sdk_mcp_request`), so it works unchanged inside the bubblewrap jail (no fs/net needed) and only ever writes to THIS session. Notes live on the new migrated `threads.session_notes` column (scoped to one topic — the #2 isolation invariant holds), are size-capped at 16 KB by trimming the oldest whole lines (`engine._apply_session_note`, mirrors the #314 cap), and are re-injected into the system prompt each build (`_session_notes_block`, BOTH modes) as explicitly LOW-AUTHORITY continuity context — never instructions — so a note that entered via web content (indirect prompt injection) cannot escalate into a command. The tool is auto-allowed (`allowed_tools` + `permissions.SAFE_TOOLS`) so it never prompts, and it bypasses the Tools page / per-user tool-cap (always on; it has no external effect). The engine's `on_remember` hook (`sessions.py` → `db.set_session_notes`) persists the updated blob immediately, so it survives a client-reaper rebuild. `/forget` clears a topic's memory (reports the size); `/memory` now shows the saved size. New `engine._remember_tool` / `_memory_server`, `db.set_session_notes` + `ThreadState.session_notes`, `/forget` command, `forget.*` + `memory.notes` i18n (en+ru), data-model.md column doc. compile + import + ruff + suite 262 green (+focused tests: append/replace/empty/cap policy, low-authority injection both modes, tool exposed+auto-allowed+SAFE, handler persist/replace/reject-empty/cap end-to-end); live restart "Run polling"; production migration confirmed (`session_notes` column present).
<!-- SECTION:NOTES:END -->

