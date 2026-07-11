---
id: TASK-167
title: "Live context size in the working plate"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 167
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
While generating, the plate shows the live context size for big sessions; owner usage is on two clean lines.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
New `ctx_status` setting (forced ON / delegate-to-disable). The context size is captured at each turn END (`session.context_usage()` — client idle, so safe) onto `rec.last_context_tokens`, and shown in the NEXT turn's "Working…" plate once ≥ 50k (`stream.context`). Avoids risky mid-stream polling. Also: owner usage in the plate + footer now shows **5h and 7d on two lines** (`usage.footer_line(sep="\n")`).
<!-- SECTION:NOTES:END -->

