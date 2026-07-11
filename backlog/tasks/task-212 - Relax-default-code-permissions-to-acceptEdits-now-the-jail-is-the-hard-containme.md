---
id: TASK-212
title: "Relax default code permissions to `acceptEdits` now the jail is the hard containment layer"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 212
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Code sessions run file edits and everyday shell commands without an approval tap by default — only push/publish, remote-access, and destructive commands still ask. The sandbox is the hard safety boundary; the prompt now just guards actions you might not intend.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
With #119 (per-uid FS confinement, egress allowlist, brokered token, seccomp, resource caps) enforcing host/cross-session safety, the default `permission_mode` moved from `default` (prompt every non-safe tool) to `acceptEdits`. New `permissions._bash_needs_approval` is a fail-safe denylist: under acceptEdits ordinary in-jail work (ls/build/test/git status/file edits) auto-runs, while push-class / outbound-with-creds (`git push`, `gh`, npm/pnpm `publish`, `twine upload`, `docker push`, `ssh`/`scp`, remote `rsync`) and destructive ops (recursive `rm`, `git reset --hard`, `git clean -fd`, `git restore`, `git checkout -- `, `dd`/`mkfs`/`shred`/`truncate`) still prompt — the confused-deputy / prompt-injection actions the jail permits but the owner may not intend. Secret-using detection deliberately omitted: secrets are env vars (a regex gate is bypassable / false comfort) and a secret only harms by leaving the jail, which egress already gates. UI fallbacks, the non-owner soft-revoke baseline, and perm-mode help copy updated to match; full-access (`/auto`) unchanged. +classifier tests. py_compile + import + pytest (151) + ruff.
<!-- SECTION:NOTES:END -->

