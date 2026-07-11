---
id: TASK-186
title: "Pluggable agent backend — drive coding agents OTHER than the `claude` CLI behind one adapter"
status: Deferred
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 186
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
_Priority P3 · Effort XL · deferred._

The engine is hardwired to the `claude` CLI / Agent SDK (`engine.py`). A thin agent-adapter layer (one interface for spawn / stream / tool-permission / resume) would let the same Telegram front-end drive other local coding agents. Big surface and no demand yet, and it cuts against the subscription-only + deep-sandbox focus — every backend needs its OWN auth + jail + billing story (and our P0 is subscription-only, no API key). Parked until there's a concrete second backend worth wiring; if so, the boundary to carve is the `engine.ClaudeSession` interface.
<!-- SECTION:DESCRIPTION:END -->

