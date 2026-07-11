---
id: TASK-304
title: "Restructure (#302) left stale doc cross-references and smoke commands"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 304
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Restructure (#302) left stale doc cross-references and smoke commands
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The #302 restructure moved files but left several doc references at their pre-move paths. Repointed all: `docs/isolation.md`'s 7 `deploy/*` links gained the `../` prefix (the doc moved into `docs/` while `deploy/` stayed at repo root — matches the file's existing `../AGENTS.md` link); README's bottom-of-file module links now point at `app/watchdog.py` and `app/core/token_refresh.py`; `docs/CONTRIBUTING.md`'s pre-PR smoke block was synced to AGENTS.md §3 (`compileall -q app conftest.py` + the package-qualified `import app.config, app.storage.db, …` line, replacing the stale `py_compile *.py` + bare-name imports). Verified by a repo-wide relative-link audit (all targets resolve) + the §3 smoke (compileall + import + 229 tests + ruff clean).
<!-- SECTION:NOTES:END -->

