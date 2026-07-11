---
id: TASK-134
title: "`big_memory` 1M context was a no-op under the subscription"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 134
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
big_memory now delivers the real 1M context window on Opus (Sonnet needs paid credits; Haiku unsupported).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Root cause: `betas=["context-1m-2025-08-07"]` is IGNORED under OAuth ("Custom betas are only available for API key users"). Fix: 1M is now requested via the **`[1m]` model-id suffix** (`engine._one_m_model`), not `betas` (both commented out). Verified live under THIS subscription: Opus `[1m]` works (auto-included on Max, no usage-credits, `service_tier:standard` → subscription-billed); Sonnet `[1m]` → "API Error: Usage credits required for 1M context" (PAID, off by default); Haiku has no 1M variant. So `[1m]` is applied to **Opus only** by default, widenable via env `BIG_MEMORY_1M_MODELS` for credit-enabled deployers. memory.show/on labels + AGENTS corrected to be accurate. Unit-tested (tests/test_engine.py).
<!-- SECTION:NOTES:END -->

