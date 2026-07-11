---
id: TASK-102
title: "Per-user access level — chat-only vs chat+code"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 102
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Per-user chat-vs-code access — chat-only users can't create/use code sessions or see code commands.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Allowlist rewritten to a per-entry record map (`allowlist.py`, v2 JSON, fail-closed, 13 unit tests) with a per-user `level` (`chat`/`code`); legacy `{ids,usernames}` migrate to `code`; owner always `code`. Enforced by gating code-session CREATION (`_do_new`, `/newcode`, the `/new` + `/sessions` choosers) and switching INTO / running a turn in a code session (`_access_block` in `on_text`/`_submit`) for non-code users. `/level @user chat | code` changes it; `/users` shows it. The default `/` command menu omits code-mode commands (`/newcode`,`/files`,`/permissions`,`/maxturns`) so chat-only users don't see them (owner chat scope shows all).
<!-- SECTION:NOTES:END -->

