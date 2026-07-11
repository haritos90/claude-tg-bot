---
id: TASK-252
title: "Comment-accuracy and spec-voice nits across sessions/sandbox/rich-spec/broker"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 252
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Internal comment/doc cleanup only — no user-facing change.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Four no-behavior corrections: `sessions.py` key-token example `":down :enter"` → `".down .enter"` (the `.` prefix is used because `:` triggers Telegram emoji search); `deploy/sandbox-claude.sh` comment "INTERACTIVE login bash" → "INTERACTIVE bash (`-i`, non-login)" to match the actual flags; `rich-message-spec.md` first-person "we pass…/we do NOT yet drive…/we do not add" → declarative spec voice; `deploy/cred-broker.py` dropped the duplicated `was \`base.startswith(p)\`` prose (the canonical `# was:` line still records the old code). py_compile + bash -n + import + ruff clean; suite 167 passed (1 pre-existing PIL font failure); live restart "Run polling".
<!-- SECTION:NOTES:END -->

