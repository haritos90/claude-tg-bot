---
id: TASK-316
title: "Thinking gerunds expanded to 30 per locale; parity test added"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 316
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The "thinking…" animation now rotates through 30 varied words in each language, and a test keeps the lists from drifting out of sync again.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The rotating `<tg-thinking>` placeholder gerunds (`stream.thinking_words`) had unequal lengths across locales (17 en vs 12 ru) with no test to catch it. Expanded both lists to 30 distinct gerunds and added a test asserting equal count across all locales (and == 30), so a future length drift fails the suite. compile + import + ruff + suite 234 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

