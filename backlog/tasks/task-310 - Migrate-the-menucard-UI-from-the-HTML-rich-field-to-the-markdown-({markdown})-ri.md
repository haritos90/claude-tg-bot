---
id: TASK-310
title: "Migrate the menu/card UI from the HTML rich field to the markdown (`{\"markdown\"}`) rich field where markdown has an equivalent"
status: Deferred
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 310
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
_Priority P3 · Effort XL · deferred._

Re-parked after VERIFYING the migration is genuinely 1:1: every format tested (inline code, bold, native tables, checklists, code blocks — both parse to `{"type":"pre","language":…}` — and the `<br>`↔`  \n` two-trailing-space line-break equivalence) maps cleanly between the rich html and markdown fields; the ONLY html-only construct is `<tg-thinking>` (draft). Still an XL, escaping-sensitive refactor (~105 `escape_html` sites moving 3→18 special chars) with NO visual gain, so not worth doing now. The format BUGS the investigation surfaced in the CURRENT implementation were fixed separately (#339). Verified rules in `docs/rich-message-spec.md`; full inventory in Details.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
**#310 — menu/card UI: HTML rich field → markdown rich field** (P3 · XL · ux)

**Goal.** `InputRichMessage` (Bot API 10.1) takes EITHER `{"html"}` OR `{"markdown"}`; both render to the SAME native rich view (no visual difference — confirmed on-device). The UI chrome (menus/cards) is built in HTML; the markdown rich field is already proven in production — the streamer's answer body / final commit, the live TODO card, and the shell keypad all send `{"markdown"}` with inline keyboards + in-place edits. Principle to apply: **HTML stays ONLY where markdown has no equivalent**; everything else moves to markdown for one consistent format.

**Scope — Telegram-bound output ONLY.** Every bit of the bot's HTML is sent to Telegram: the rich `{"html"}` field and `parse_mode="HTML"` are the only HTML sinks (verified — the bot writes NO HTML files / reports / exports; even `/history export`'s `escape_html` is for the Telegram error message, not the file). So "exclude non-Telegram content" removes nothing — docs (`TODO`/`docs/`/`README`) and code comments were never migration targets. Everything below is Telegram-bound.

**Genuinely HTML-ONLY — the ONE hard blocker:**

- `<tg-thinking>` "Thinking…" draft block — `streamer.py` ~526, ~732, ~851 (3 sites, ONE feature). Per `docs/rich-message-spec.md` it is a custom HTML tag, draft-only (`sendRichMessageDraft`); the spec gives NO markdown form. MUST stay HTML. **This is the only construct in the whole Telegram surface with no markdown equivalent.**

**One thing to verify (likely fine, probably not a blocker):**

- `tg://user?id=<id>` deep-link — `handlers.py:3833` (its sibling `https://t.me/<user>` at `:3831` is plain md `[text](url)`). Classic MarkdownV2 already supports `[mention](tg://user?id=…)`, so the rich markdown field very likely accepts it too — quick-verify on the rich field; worst case keep this one anchor as a tiny HTML island or degrade to a plain `@username`.

**MIGRATABLE — markdown equivalent exists (~95% of the surface):**

- **i18n catalog** (`app/i18n.py`): ~208 entries carry HTML, using ONLY three tags — `<code>` (~324), `<b>` (~322), `<i>` (~44) summed across en+ru (AST count over the `CATALOG` dict; an earlier line-grep of ~533 entries / ~666 tags over-counted comment lines + both lang lines). Each maps 1:1 to GFM: `<b>`→`**`, `<code>`→`` ` ``, `<i>`→`*`. No `<a>` / `<pre>` / lists / tables live in i18n. Mechanical conversion, both languages.
- **Menu send path**: `_send_menu` (`handlers.py:351`, 17 call sites) + `_edit_menu` (`:377`, 38 sites) = **55 surfaces funnelling through 2 helpers**. Flip the field `{"html"}`→`{"markdown"}`, CONVERT the `\n`→`<br>` transform (#202) into `\n`→`  \n` (two-trailing-space hard break — the VERIFIED 1:1 equivalent of `<br>`; a single `\n` is a SOFT break = space in BOTH rich fields, so the line-break transform must NOT just be dropped — see `docs/rich-message-spec.md` "Line breaks"), and switch the classic fallback `parse_mode="HTML"`→`"MarkdownV2"`.
- **Other html `SendRichMessage`/`EditRichMessage`**: command-reply (`handlers.py:287`), `reply_rich_html` /status checklist (`:338` def, called `:4470`; `<ul>`/`<li>`→md `-`), userstats native table (`:4652`).
- **markup.py builders → GFM**: `table_to_rich_html` (`:451`) + `_cell_rich_html` (`:441`) + `_render_table_cards` (`:173`) → GFM pipe tables / `**`; `_render_table_pre` (`:153`) → fenced block. The native-table HTML send in the streamer (`streamer.py:911`, via `table_to_rich_html`) needs a new `table_to_markdown(rows, aligns)` helper — it is a SECONDARY path (the primary tables already stream + commit as markdown).
- **Stays as-is (not menu html)**: `md_to_html` (`markup.py:789`) + `_blockquotes_to_html` (`:752`) are the model-reply HTML / classic-fallback path; `_latex_to_unicode` (`:699`) is a format-agnostic text transform (no tags).

**THE CORE WORK + RISK — escaping (build this FIRST):**

- **105 interpolation sites** use `markup.escape_html` (91 in `handlers.py` + 14 elsewhere) to escape dynamic values before formatting into templates: session/user names, `@usernames`, cwd/paths, file trees, search keywords (`handlers.py:1952`), model strings, `str(exc)` error text, schedule specs, secret names, dates.
- **NO GFM/markdown escaper exists** in the project — `markup.escape_html` handles only 3 chars (`& < >`).
- The markdown rich field follows GFM/MarkdownV2 rules: ~18 special chars must be escaped anywhere (`_ * [ ] ( ) ~ ` `` ` `` `> # + - = | { } . !`), or a value mis-renders (a session named `my_project` → `myproject` in italics) or the send 400s. This **3→18 jump across 105 sites is the dominant hazard** — failures `escape_html` cannot currently produce.

**Already markdown (no work):** streamer answer body (`streamer.py:558`), final commit (`:1090`), TODO card (`:1049`/`:1059`), shell keypad/detach/re-attach (`handlers.py:461`/`3185`/`3200`) — these prove the markdown field works with keyboards + edits.

**Fallbacks (lower priority):** ~22 classic `parse_mode="HTML"` sends + the legacy `md_to_html` chunk path in `streamer._commit` are degradation / "rich-send failed" paths; flip to `MarkdownV2` or leave — per the principle they may stay, since they only run when the rich send already failed.

**Recommended order:** (1) build + unit-test a hardened GFM/MarkdownV2 escaper; (2) PILOT one card (`/users`) end-to-end — escaper + convert its 3-tag strings + its escape sites + a render edge-case test (a name with `_`/`*`, a path); (3) if clean, convert i18n (mechanical) + the 2 menu helpers + CONVERT the `<br>` transform to `  \n` (two trailing spaces — verified 1:1, #339; NOT a drop); (4) sweep the 105 escape sites; (5) add `table_to_markdown` for the native-table sends; (6) verify `tg://` link support in the markdown field, else keep that island; (7) keep `<tg-thinking>` as the one HTML-only draft block.
<!-- SECTION:NOTES:END -->

