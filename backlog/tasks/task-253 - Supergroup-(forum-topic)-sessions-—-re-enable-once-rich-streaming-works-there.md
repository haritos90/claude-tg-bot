---
id: TASK-253
title: "Supergroup (forum-topic) sessions — re-enable once rich streaming works there"
status: Deferred
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 253
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
_Priority P2 · Effort L · deferred._

Rich-draft streaming is private-chat-only (`TEXTDRAFT_PEER_INVALID` in supergroups, #3/#39), so the supergroup surface can't get the rich UI; not touching this area for now. The active forum-topic implementation is commented out (DM-only): `_do_new` create, `_do_rename` rename, and `cmd_close` now reply with `topic.disabled` instead of calling `create_forum_topic`/`edit_forum_topic`/`close_forum_topic` (each old block kept commented with a `#253` ref). The dormant topic-routing (sign-convention keys, `message_thread_id` send-kwargs) is left in place as a no-op for DM. Revive: uncomment those three blocks (+ verify routing/streaming) when supergroup rich streaming is solved.
<!-- SECTION:DESCRIPTION:END -->

