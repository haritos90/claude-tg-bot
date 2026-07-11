---
id: TASK-333
title: "/whois — owner lookup: user → sessions → workdir → transcript"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 333
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The owner can type `/whois <id>` to see all of a user's sessions and exactly where each one's files and transcript live.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
New owner-only `/whois <user_id>` (arg-capture #101: prompts for the id if none given) maps a user to their sessions — each row shows the mode glyph, name, public ULID, the on-disk workdir (`cwd`), and transcript status (📝 live / 📦 archived / — none). Read-only; built so "where is user X's chat" is one command instead of a hand SQLite query + filesystem grep. Uses `browse_threads` + `session_pubid`; transcript presence derived from `<sid>/state/<encoded-cwd>` (live) or `_archive/<uid>/<pubid>-*.tar.gz`. Registered in `commands.py` (owner tier), i18n (en/ru), `_run_pending` arg-capture, and documented in `menu.md` Tier F. compile + import + ruff + suite 248 green; live restart "Run polling"; verified its render against the live DB.
<!-- SECTION:NOTES:END -->

