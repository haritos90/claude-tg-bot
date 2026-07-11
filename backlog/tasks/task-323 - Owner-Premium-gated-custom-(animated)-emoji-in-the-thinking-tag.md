---
id: TASK-323
title: "Owner-Premium-gated custom (animated) emoji in the thinking tag"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 323
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The "thinking…" indicator can show fancy animated custom emoji when the bot owner has Telegram Premium, falling back to normal emoji otherwise — set the emoji ids in `THINKING_EMOJI_IDS` to turn it on.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Logic to detect whether the bot OWNER has Telegram Premium and swap the thinking-tag icons (💭 / 🔎) to CUSTOM animated emoji accordingly. Owner premium is auto-detected from the owner's own messages (`from_user.is_premium` → `streamer.set_owner_premium`, updated live in `_ensure_state`); `streamer._emoji(uni, role)` emits `<tg-emoji emoji-id="…">uni</tg-emoji>` ONLY when the owner is premium AND a `custom_emoji_id` is configured for that icon (else the plain unicode — the required fallback; viewers never need Premium to see custom emoji animated). Ids come from the `THINKING_EMOJI_IDS` env (`think:<id>,search:<id>`, e.g. the AIActions pack); empty by default → unicode, zero behaviour change. A draft the server rejects self-heals back to unicode for the turn (`_custom_emoji_failed`), so a bad id / unsupported-in-draft can't blank the indicator. +test (premium+id → tg-emoji; else / self-heal → unicode). Documented in `rich-message-spec.md`, incl. the not-yet-verified-live caveat that the owner-Premium pathway is documented for SENT messages and may not cover drafts (the Fragment-username pathway is the safe one). compile + import + ruff + suite 237 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

