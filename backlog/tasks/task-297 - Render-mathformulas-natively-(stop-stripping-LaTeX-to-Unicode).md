---
id: TASK-297
title: "Render math/formulas natively (stop stripping LaTeX to Unicode)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 297
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The bot now renders real formulas — `$E=mc^2$` inline and `$$…$$` as a centered equation — instead of flattening math to plain Unicode.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Reverses #43/#51: those forced plain Unicode because Telegram couldn't render math. Bot API 10.1 now renders it NATIVELY — verified LIVE against the API (a `sendRichMessage` probe + the parsed `rich_message` JSON, confirmed on-device): `$…$` → an inline `mathematical_expression`, `$$…$$` → a block one (a ```` ```math ```` fence is equivalent); `\(…\)`, `\[…\]` and an HTML `<math>` are NOT parsed (they arrive as literal text — `<tg-math>` works in the HTML form). The reply path already streams + persists as `{"markdown"}` (#176), so LaTeX passes straight through on BOTH the draft and final send with no new handling; an unclosed `$$` at the frontier just shows raw until it closes (same as a half-typed `**bold**`, harmless — no clip-partial-math needed, unlike the table case #237). Flipped `engine.CHAT_SYSTEM_PROMPT` + `agent_context.md` from "never use `$…$`, write Unicode" to "write `$…$` inline / `$$…$$` block LaTeX, escape a literal dollar as `\$`"; old text kept commented with a #297 ref. `markup._latex_to_unicode` (#51) stays as the classic-HTML FALLBACK degradation only (documented in `markup.md`). Added a re-verifiable `deploy/verify-rich-draft.py --math` mode and a math section to `rich-message-spec.md`. py_compile + import + ruff + suite clean; live restart "Run polling"; verified on-device.
<!-- SECTION:NOTES:END -->

