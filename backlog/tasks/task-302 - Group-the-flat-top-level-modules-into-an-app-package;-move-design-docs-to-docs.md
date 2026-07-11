---
id: TASK-302
title: "Group the flat top-level modules into an `app` package; move design docs to `docs/`"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - build
dependencies: []
ordinal: 302
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
No user-facing change — internal repository restructure: code grouped under `app/` (run via `python -m app`), design docs under `docs/`.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The 23 flat top-level modules were grouped into the `app` package: `app.core` (engine, sessions, token_refresh, schedules + the co-located `agent_context.md` runtime asset), `app.storage` (db, archive, usage), `app.access` (access, allowlist, permissions, settings_schema), `app.telegram` (handlers, commands, streamer, rich_message, markup, svg_image, table_image), with the bootstrap modules (bot, watchdog, config, i18n) at the package root. Entry point is now `python -m app` (`app/__main__.py` → `app.bot.main()`); the systemd unit + template + `install-systemd.sh` were repointed (the manual-copy `pkill` now excludes the unit's MainPID, since `-m app` makes the manual/service cmdlines alike). All 75 intra-project import sites were rewritten to package-qualified form by a line-anchored script (which skipped a `from usage.ts` docstring). `engine`/`bot` resolve the repo-root `deploy/` scripts via a new shared `app.REPO_ROOT`/`DEPLOY_DIR`; `agent_context.md` co-locates with `engine` so its sibling-`__file__` load is unchanged; `commands` and `handlers` stay siblings in `app.telegram` so the registry drift-scan `with_name("handlers.py")` still resolves. Design docs moved to `docs/` (data-model, isolation, menu, markup, rich-message-spec, CONTRIBUTING, SECURITY); README/AGENTS/CLAUDE doc links repointed (and intra-`docs/` links to root-staying files prefixed `../`); CI byte-compile + import-smoke and the PR/issue templates updated; `pyproject` gained `pythonpath=["."]` so tests import via `app.*`. README §Project structure + directory tree and AGENTS §3/§4 refreshed to the package layout. py_compile + import smoke + ruff clean; suite 229 passed; live restart confirmed "Run polling" with cred-broker/seccomp/egress all resolving from the new layout.
<!-- SECTION:NOTES:END -->

