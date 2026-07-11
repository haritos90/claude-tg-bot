---
id: TASK-345
title: "Chat session stuck on \"Not named yet\" when the engine never wrote an ai-title (trivial / API-errored opening)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 345
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A chat session no longer gets stuck showing "Not named yet": when the assistant's own auto-title is missing — e.g. you opened with just a greeting or the first replies hit a server error — the session is named after your first real message instead.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The turn-end auto-namer adopted Claude Code's transcript `ai-title` but had no fallback. The engine writes that title from the conversation OPENING, so a session whose first turn(s) errored (API 5xx / Overloaded) or opened with a contentless greeting never got one — and because the session then held real content, the zero-request empty-GC wouldn't reap it either, so it lingered forever on the `Not named yet` placeholder (auto-naming worked for every other session: the bot only adopts a title the engine actually wrote). `_read_ai_title` is now `_read_session_title`, returning `(ai_title, fallback)` in ONE pass (no second scan of the #285-unbounded transcript); the namer uses `ai_title or fallback`, where the fallback is the first SUBSTANTIVE user message — bare greetings / probes / acks and the injected recap prompt are skipped via a letter-count + prefix filter (`_topic_from_text`), capped at `_AI_TITLE_MAX`. Priority, highest first: a user `/rename` (pinned, `name_auto=0`) > the agent's own ai-title > the message fallback > the auto `Not named yet` placeholder — the fallback writes `manual=False`, so when the agent DOES write an ai-title on a later turn it still supersedes the fallback, and a genuinely contentless session (only a greeting) stays unnamed by design. Existing stuck sessions self-heal on their next message (they keep `name_auto=1`, so they are never pinned over). compile + import + ruff + suite 257 green (+ focused tests: greeting/recap skip + cap, ai-title precedence, fallback on an errored/trivial opening, all-trivial→unnamed, missing-file/empty-args, end-to-end fallback rename, AGENT ai-title overriding a prior fallback across turns, db-level auto-over-auto override); live restart "Run polling".
<!-- SECTION:NOTES:END -->

