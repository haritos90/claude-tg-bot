---
id: TASK-195
title: "Seccomp blob write was non-atomic and a stale blob was never cleared"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 195
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Hardening: the sandbox syscall-filter file is now written atomically (no truncated/half-written filter after a crash) and a stale filter from a different CPU architecture is cleared instead of mis-applied.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`deploy/make-seccomp.py` wrote the BPF blob with a plain `open(...,"wb")` — a crash mid-write would leave a TRUNCATED program that bwrap loads as malformed. And on a non-x86_64 arch the script wrote nothing while `bot.py` still forwards any pre-existing blob (`os.path.exists`), applying an arch-mismatched filter. Fix: write to `<out>.tmp.<pid>` then `os.replace` (atomic within the fs; `fsync` before replace), and on the unsupported-arch path `os.remove` any existing output (suppressing OSError) so a stale x86 blob can never be applied elsewhere. Verified: regen produces a byte-identical 272-byte blob with no leftover temp; live restart recompiled it cleanly.
<!-- SECTION:NOTES:END -->

