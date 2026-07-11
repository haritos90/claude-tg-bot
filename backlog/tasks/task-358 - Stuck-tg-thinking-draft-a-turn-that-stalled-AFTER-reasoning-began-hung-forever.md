---
id: TASK-358
title: "Stuck `<tg-thinking>` draft: a turn that stalled AFTER reasoning began hung forever"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 358
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Fixed a rare hang where the live "Thinking…" indicator could stay on screen indefinitely if the model stalled right after it started thinking; such a turn now ends with a clear "service unavailable" notice within a few minutes instead.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Specific one-off, diagnosed on the LIVE process: a chat turn made completed model calls (broker logged `/v1/messages -> 200`) but the jailed `claude` CLI then sat idle (`do_epoll_wait`, no sockets) without emitting a final result, so the engine's stream wait — UNBOUNDED once any event had arrived — hung indefinitely while the streamer's ~20s keepalive kept the `<tg-thinking>` draft animating. (The normal expiry that always worked never got a chance: a draft can't be force-cleared via the Bot API — verified against the live docs, there is no end/clear method and empty content shows "Thinking…", not a clear — it only self-expires ~30s after the LAST draft send, which the keepalive keeps pushing back.) The first-token watchdog (#343) didn't catch it because a `thinking_delta` IS a `StreamEvent`, so it disarmed the moment reasoning started. Fix: a second `_STALL_TIMEOUT_SEC` (env `MODEL_STALL_TIMEOUT_SEC`, default 180s) bounds each inter-event wait while the turn is still in the THINKING phase (progressed, but no ANSWER content yet — text/tool/result tracked via a new `_answered` flag); once real answer content starts it stays unbounded (a long tool call / build legitimately emits nothing for minutes). On fire it reuses the existing path — aclose the stream, drop the client (kills the wedged subprocess), surface `err.service_unavailable`, which the streamer commits via `finish()` as a real `sendRichMessage` — and that final message clears the `<tg-thinking>` draft (the same path that ends every normal turn), instead of the turn hanging forever. (Empirically a draft is NOT reliably auto-expired — it clears only when a real message lands — so an orphaned draft from a restart that cancelled an unfinished turn (the graceful ~40s drain timed out) needs the next message to clear; #358's value is preventing the wedge so the turn reaches `finish()` on its own.) The live wedge was cleared by the restart that deployed this. 2 focused tests (reasoning-then-silence times out; reasoning-then-answer does NOT false-fire across a gap > the window); `docs/rich-message-spec.md` updated with the verified no-force-clear draft semantics. compile + import + ruff + suite 266 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

