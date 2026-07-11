---
id: TASK-335
title: "`/whois` used a different cwd→transcript encoder than the title reader; header counted unlisted rows"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 335
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Owner `/whois` reliably finds each session's transcript (the path encoding matches what's on disk), and its header count matches the rows it lists.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Two `/whois` fixes. (1) Transcript detection encoded the cwd with `re.sub(r"[^A-Za-z0-9]","-",cwd)` while the ai-title reader used `cwd.replace("/","-")`; the two agree only when `/` is the cwd's sole punctuation and diverge for any `.`/`_`/other char — so one resolved the WRONG `state/<enc>` dir. Consolidated on ONE shared encoder matching what claude writes on disk (verified against the live layout `<sid>/state/<re.sub-encoded cwd>`): new `archive.encode_workdir` + `archive.live_transcript_dir`, used by BOTH the ai-title reader and `/whois` (the #332 migration's identical inline `re.sub` is annotated as a keep-in-sync copy, to avoid importing `archive` into the storage leaf). (2) `whois.head` printed `n=total` (the full COUNT) while the loop lists only the capped `rows` (limit=500) — now reports `n=len(rows)` so the header matches the visible list. The ai-title test helper also moved to the shared encoder (it had hard-coded the old `replace` form — the latent bug, masked because the old reader was wrong the same way). compile + import + ruff + suite 249 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

