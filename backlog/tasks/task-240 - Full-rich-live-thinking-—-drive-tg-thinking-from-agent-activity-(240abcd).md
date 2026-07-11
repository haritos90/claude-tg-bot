---
id: TASK-240
title: "Full-rich live \"thinking\" — drive `<tg-thinking>` from agent activity (240a/b/c/d)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 240
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The "thinking" indicator now shows the model's live reasoning as it unfurls, then is replaced by the answer — and never stays in history.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The draft-only `<tg-thinking>` block (Bot API 10.1) is a live "what the agent is doing" indicator that self-cleans at finish. 240a (DONE): rotating Claude-Code gerunds before first content. 240b (DONE): live TOOL phase ("⚙️ Running pytest…") from the `tool` event via `streamer.set_phase`. 240d (DONE via unicode): plain-unicode phase emoji (the AIActions pack is premium custom emoji a bot can't render). **240c (this change): stream the model's REASONING/extended-thinking** — `engine.run` surfaces `content_block_delta.thinking` as a new `thinking_delta` event (not added to the answer text); `sessions._run_one` forwards it to `streamer.add_reasoning`, which accumulates the tail and shows it in `<tg-thinking>` ("💭 …unfurling…"). Render priority in the no-body draft branch: reasoning → tool phase → gerund; cleared once real answer content streams (and on segment reset). Tail-capped; DM-draft-only; best-effort. DRAFT-ONLY throughout — `finish()` stays `{"markdown": full_text}` with no thinking block. +streamer unit test. py_compile + import + ruff clean; **suite 178 passed**; live restart "Run polling". On-device render of streamed reasoning pending (needs an extended-thinking turn).
<!-- SECTION:NOTES:END -->

