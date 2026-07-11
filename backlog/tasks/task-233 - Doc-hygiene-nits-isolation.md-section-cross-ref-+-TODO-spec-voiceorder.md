---
id: TASK-233
title: "Doc-hygiene nits: isolation.md section cross-ref + TODO spec-voice/order"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 233
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Documentation only — the sandbox reference's section cross-ref is correct, the changelog reads in neutral spec voice, and the Backlog is back in ascending-ID order.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Three documentation fixes from the #231 diff: (1) `isolation.md` intro cited "the egress allowlist + cgroup DoS limits (§5–§6)" — wrong sections (egress is §4, DoS is §6, §5 is per-session secrets); corrected to `(§4 + §6)`. (2) the #225 Closed Resolution closed with first-person narration ("our") that violates spec voice; restated neutrally to name the credential broker. (3) the Backlog table + Details blocks had #227 ahead of #226 (out of ascending-ID order per the line-32 rule); reordered both so the tail reads 226, 227, 229, 234.
<!-- SECTION:NOTES:END -->

