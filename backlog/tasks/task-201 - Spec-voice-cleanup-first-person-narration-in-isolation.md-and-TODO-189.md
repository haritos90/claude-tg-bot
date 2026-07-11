---
id: TASK-201
title: "Spec-voice cleanup: first-person narration in isolation.md and TODO #189"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 201
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
No user-facing change — documentation voice cleanup.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Removed first-person voice from two spec surfaces. `isolation.md`: "We did **not** add an 'insecure' flag" → "No 'insecure' flag is added"; "we use `iptables -m cgroup --path`" → "the egress rule uses `iptables -m cgroup --path`". TODO #189 (Deferred reason + Details): "Our reaper" → "The reaper", "our default" → "the project default", "Marginal for us" → "Marginal here", "we deliberately favour" → "the project deliberately favours". Verified no `we/our/us` remains in either. Docs-only, no code change.
<!-- SECTION:NOTES:END -->

