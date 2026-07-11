---
id: TASK-151
title: "Owner-configurable, derived access model"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 151
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Owner-configurable, derived access model
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Shipped 151a/151b + hub enforcement: `Access` (Hidden/Read-only/Delegated) base (Table 23 defaults, owner-overridable) + per-user exceptions; derived `effective_access`/`resolve_effective`; owner Global-tab option-admin + per-user access card; unit-tested. Consumption-time derivation + capability-gate fold-in split to #161.
<!-- SECTION:NOTES:END -->

