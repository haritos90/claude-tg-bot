---
id: TASK-390
title: >-
  Nits: refresher exception-sweep escalation parity, render_within_limit
  UTF-16/hard-cut headroom, DNS self-heal operator note
status: Done
assignee: []
created_date: '2026-07-22 08:34'
updated_date: '2026-07-22 08:51'
labels:
  - reliability
dependencies: []
priority: low
ordinal: 28362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Small robustness and documentation follow-ups from reviewing the token-refresh + interleave hardening batch. None is a data-loss or security issue.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 token_refresh.py:303 — the except-Exception sweep increments fails so a persistent non-timeout error escalates to the consecutive-fail WARNING like the fail/timeout paths
- [ ] #2 markup.py:1251/1265 — render_within_limit bounds against UTF-16 units (or adds headroom) so a 4096-code-point piece with supplementary-plane characters stays within Telegram's ceiling, and the last-resort hard-cut re-verifies its output is within hard_limit
- [ ] #3 docs/troubleshooting.md — a short OAuth-refresher note: a permanently DNS-wedged refresher self-heals via executor recreate; the sweep-exceeded and heartbeat-gap signals indicate a wedge; a restart is only needed for a revoked login (persistent 401s)
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
token_refresh.py: the except-Exception sweep now increments fails so a persistent unexpected exception feeds the consecutive-fail escalation (parity with the fail/timeout paths; a healthy ok / skip-Ns-left still resets). markup.py: render_within_limit measures Telegram's UTF-16 code units via a new _tg_len helper instead of code points, and the last-resort hard-cut now shrinks its step until every rendered piece is re-verified within the ceiling (the old fixed-step version is kept commented with a #390 ref). docs/troubleshooting.md: a new OAuth-refresher section maps the three log signals (sweep-exceeded self-heal, missing heartbeat = dead loop, repeated 401 = revoked login) to their actions.
<!-- SECTION:NOTES:END -->
