---
id: decision-17
title: "English-only repo; user-facing strings only through i18n"
date: '2026-07-04 00:00'
status: accepted
---
## Context

The repo may be released publicly, so mixing languages in code/docs/comments would be unmaintainable — but the bot must speak the user's language.

## Decision

Everything in the repo (code, comments, docs, identifiers, task files, commit messages) is ENGLISH. User-facing strings are localized ONLY through `i18n.py` (`en` is the source column; `ru` is a translation layer). Non-English text is allowed in EXACTLY three translation surfaces — `i18n.py` `ru` values, `commands.py` `ru` labels, `menu.md` bilingual tables — and nowhere else, not even to 'describe' an i18n change.

## Consequences

- A publicly releasable, single-language codebase with full localization.
- Handlers never hardcode a user-facing string; they render `i18n.t(key, lang, ...)`.
- Describing an i18n change references the catalog key + English, never the localized literal.

**Source tasks:** #63, #207, #287, #294, #336
