---
id: TASK-314
title: "Code sessions: a real project CLAUDE.md in the working directory"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 314
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Code sessions now honor a CLAUDE.md in their working folder — write project conventions or build steps once and the agent follows them on every later turn, just like real Claude Code.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A code session now reads a `CLAUDE.md` from the agent's working directory and injects it into the system prompt, so a code user (or the agent itself) can keep durable project instructions like a real Claude Code project memory. Mirrors the owner global-memory injection (`engine._workdir_claude_block`, appended to the `claude_code` preset's `append` in `_build_options`): kept OUT of `setting_sources` (stays `[]` — the isolation invariant, never loads `settings.json`), re-read on each session build (an edit applies on the next build), code-only, capped at ~16 KB so a huge or hostile file can't blow the context or burn the shared subscription. The code addendum now tells the agent it can create/edit `./CLAUDE.md` and to offer to record "remember this" project requests there. compile + import + ruff + suite 230 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

