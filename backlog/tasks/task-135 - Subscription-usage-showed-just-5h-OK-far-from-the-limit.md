---
id: TASK-135
title: "Subscription usage showed just \"5h OK\" far from the limit"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 135
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Subscription usage showed just "5h OK" far from the limit
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`usage.fetch_account_usage` GETs `/api/oauth/usage` (the source Claude Code's /usage reads) with the OAuth bearer + `anthropic-beta: oauth-2025-04-20` — the REAL per-window % even when idle (the SDK rate-events only send it near a limit). Normalized (percent→fraction, ISO→epoch) into `rate_by_type`; a 5-min poller (`sessions._usage_poll_loop`) + a refresh on /status keep the footer/pinned live (e.g. "5h 61% left · resets 2h42m"). Read-only GET, fail-soft. Unit-tested.
<!-- SECTION:NOTES:END -->

