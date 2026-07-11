---
id: TASK-33
title: "verify the SDK usage-dict keys feeding `db.add_usage`"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 33
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
verify the SDK usage-dict keys feeding `db.add_usage`
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Verified: `ResultMessage.usage = data["usage"]` is the raw Anthropic API `usage` object (snake_case `input_tokens`/`output_tokens`/`cache_read_input_tokens`/`cache_creation_input_tokens`) — keys match; added a sync-keeping comment in `db.py`.
<!-- SECTION:NOTES:END -->

