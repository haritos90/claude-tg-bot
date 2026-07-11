---
id: TASK-219
title: "acceptEdits Bash denylist missed recursive-delete and alternate command forms"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 219
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Recursive deletes (`rm -R` / `rm --recursive`), `git clean --force`, ref-scoped `git checkout … -- path`, and rsync to an ssh-alias host now correctly ask for approval instead of running without a prompt.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The #212 `permissions._bash_needs_approval` denylist auto-ran several forms of the very commands it gates: `rm -R`/`rm -Rf` (the regex was case-sensitive + short-option only) and `rm --recursive` (long option); `git clean --force` (long form); `git checkout <ref> -- <path>` (only an immediate `--`/`.` was matched); and `rsync` to an ssh Host alias (`host:/path`, no `@`). Patterns widened to the capital/long/alias forms (old patterns kept commented per the audit convention); the fail-safe PROMPT direction is unchanged and the #119 jail still backstops host damage. +7 classifier cases (in the existing parametrized lists). py_compile + import + pytest (151) + ruff.
<!-- SECTION:NOTES:END -->

