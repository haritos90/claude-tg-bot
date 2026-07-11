---
id: TASK-362
title: "Session memory (`remember` tool + agent notes) is now code-only — was attached in chat too"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 362
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The assistant's saved per-topic session memory (its own `remember` notes) is now a code-session feature for code-level users; chat sessions no longer keep or inject it.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The #352 session memory (the in-process `remember` tool + its re-injected per-topic notes) was attached in BOTH chat and code for everyone. Gated it to CODE sessions owned by a CODE-LEVEL user via a new `ClaudeSession._session_memory_on()` (`mode == "code" and user_level == "code"` — the engine already carries both, `user_level` from #276): it now guards the `remember` MCP-server registration, the `MEMORY_TOOL` auto-allow entry, and `_session_notes_block()` injection (which also self-gates, so a stored blob stays dormant in the DB). Chat's `_build_options` no longer adds the tool or the notes block; the demotion gap is closed — a user dropped code→chat gets neither on a leftover code session (matches the #283 code-feature invariant: gate on user LEVEL, not just session MODE). Handler side: `/forget` now rejects in a chat session (`common.code_only`, like `/files`/`/shell`) and is `scope="code"` so it drops from a chat user's `/` menu; the `/memory` reply's agent-notes-size suffix shows only for a code session + code-level user. Docs: `docs/data-model.md` scopes `session_notes` to code sessions, `docs/menu.md` Table 5 lists `/forget` (🟦, beside `/memory`), and the engine module comment drops the now-stale "chat's tool-free ./CLAUDE.md equivalent" rationale. Replaced lines kept as commented `was (#352)` blocks for revertibility. The two `*_both_modes` engine tests were rewritten to `*_code_only` (chat + a demoted-code session get neither tool nor notes; code + code-level gets both). compile + import + ruff + suite 269 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

