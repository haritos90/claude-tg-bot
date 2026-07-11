---
id: TASK-271
title: "Idle-started session only appeared after a typed message, not when opening /sessions"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 271
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Opening `/sessions` after a long break now immediately shows a freshly started session as current (with a small "started a fresh session" note), instead of only switching once you send your next message.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The idle→new-session rotation (#266) fired only on a conversational turn, so checking `/sessions` after a long break still showed the OLD session as current (the new one was minted lazily on the next typed message) — which read as "rotation didn't work". Generalized `_session_key_for_turn` into `_rotate_if_idle(message) -> (key, rotated)` (same cap/evict/fallback logic) and call it from `cmd_sessions` too, so opening `/sessions` after the idle window auto-starts the fresh session and shows it AS current immediately (creation happens on interaction, not only on a chat turn). Rotates at most once per gap (the new session has `last_active=0`). When that open rotates, the `/sessions` header carries a passive one-line notice (`sessions.idle_rotated`) — shown only in the card, never a push, per the no-spammy-auto-notices rule. The conversational path stays silent (wrapper drops the rotated flag). Targeted to the chat turn + the `/sessions` view (NOT every command — rotating before a state-mutating command like `/clear`/`/code` would act on a surprise empty session). py_compile + import + ruff + i18n parity clean; suite 216 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

