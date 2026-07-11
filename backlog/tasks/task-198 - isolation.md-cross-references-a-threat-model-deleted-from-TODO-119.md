---
id: TASK-198
title: "isolation.md cross-references a threat model deleted from TODO #119"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 198
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The sandbox deep-reference (isolation.md) now carries the full threat model and design rationale that previously lived only in a closed TODO task.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`isolation.md:6` pointed at "TODO.md #119 holds the threat model + design rationale", but #119's Details block (threat model, exfil-channel analysis, components, egress options) was deleted when it moved to Closed — the rationale existed nowhere. Migrated it into isolation.md as a new `## 12. Threat model & design rationale` section (assets, adversary, non-goal, the four exfil channels and the core conclusion that no egress control protects a token living inside the jail → the broker keeps it host-side; plus the domain-proxy-over-IP and cgroup-scoped-not-global rationales, cross-referencing §3/§4/§6). Rewrote it in the doc's present-tense spec voice rather than pasting the historical deliberation (options A–E "pick when reviving"), with a short historical note that the build options are settled. Fixed the line-6 reference to point at §12; AGENTS/README carried no copy of the dangling claim so needed no repoint.
<!-- SECTION:NOTES:END -->

