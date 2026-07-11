---
id: TASK-266
title: "Idle rotation: start a real NEW session (preserve the old) instead of resetting in place"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 266
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
After ~30 min idle your next message now opens a real new session (auto-named), and the previous conversation stays in your session list instead of being silently wiped — your files and old chats are kept.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
#261 reset the current session's context in place on a long idle gap — but the session list still showed its lifetime stats (requests/tokens), so it read as "same session, but memory gone" (confusing). Reworked so an idle gap starts a genuinely NEW session: the old one stays in `/sessions` with its full history, a fresh one becomes current and (via #260) auto-names itself, inheriting the old session's mode. Moved the decision UP to the handler routing layer — `_session_key_for_turn` (used by `on_text` + the attachment `_submit`, NOT by menu taps) resolves the current DM key, and if `now - last_active ≥ window` it allocates a new session and switches `dm_current`. Window resolution is the public `sessions.idle_reset_seconds(uid)` (global admin `idle_reset_sec` + per-user `idle_reset_min`). Session-cap handling: at the cap it archives the OLDEST disposable session (`_evict_oldest_empty` — non-current, non-favorite, zero usage) to free a slot; if nothing is disposable it falls back to `sessions.rotate_in_place` (clear context, keep the entry) so a session with content is never auto-deleted. The old in-place `_maybe_rotate_idle`/`_resolve_idle_reset` were removed; `last_active` stamping + the admin picker (#261) are unchanged. Supergroup topics never auto-rotate (shared resource). +tests (window resolution global/override/disable; rotate_in_place clears ids + drops client). py_compile + import + ruff clean; suite 212 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

