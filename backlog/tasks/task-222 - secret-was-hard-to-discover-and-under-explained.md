---
id: TASK-222
title: "`/secret` was hard to discover and under-explained"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 222
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`/secret` is reachable from the settings menu and has a built-in "How to use" guide (with a GitHub HTTPS setup walkthrough) in both languages.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`/secret` was registered and in the "/" command menu (code scope) but absent from the in-app `/settings` hub, and its prompt gave only a terse blurb. Added a "🔐 Session secrets" row to the hub Session tab (code only, `sx:secret`) that opens the arg-capture prompt; the prompt now carries a "📖 How to use" button → a detailed bilingual guide (`secret.guide`) with a GitHub-over-HTTPS walkthrough (fine-grained PAT → `GH_TOKEN=` → `gh`/git over HTTPS), an explicit "SSH is not supported" note, other-service examples, and a host-operator trust note. Dropped the "owner's credentials are never shared" clause from `secret.help` (a user need not know an owner exists). py_compile + i18n + commands-consistency + pytest (151) + ruff.
<!-- SECTION:NOTES:END -->

