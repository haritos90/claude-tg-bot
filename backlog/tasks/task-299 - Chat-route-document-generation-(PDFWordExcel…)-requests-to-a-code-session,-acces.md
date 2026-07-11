---
id: TASK-299
title: "Chat: route document-generation (PDF/Word/Excel/…) requests to a code session, access-aware"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 299
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In a chat session, asking for a PDF/Word/Excel/etc. now gets a clear, correct next step — code-capable users are told to /code (the bot then builds and sends the file), while chat-only users are told how to request access from the owner — instead of a refusal or a wall of raw text.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Chat is tool-free by design (no Bash/files — only read-only web tools, plus open egress and no DoS caps), so it CANNOT build a binary document (PDF/.docx/.xlsx/.pptx/CSV need code execution: openpyxl/reportlab/python-docx). Decision (weighed host-side-build and giving chat code-exec): ROUTE such requests to a code session, which already has Bash + pypi + the outbox file delivery (#187) and carries the conversation over on /code — zero new attack surface, chat stays tool-free. Made the model aware of the limit AND access-aware so it gives the RIGHT path (gate on user LEVEL, not just mode): strengthened `engine.CHAT_SYSTEM_PROMPT` with a level-AGNOSTIC note (chat can't create files; name the formats; never paste raw bytes or fake an attachment; defer the "how" to the per-session note), and extended both CHAT branches of `_session_state_note` (#276, which already injects the user's access level) — a code-access user is told to send /code and the file gets built+sent back; a chat-only user (who can't /code) is told to ask the bot's owner to grant them code access instead of being pointed at /code. Verified the three branches (chat+code → /code, chat-only → owner, code → already capable). py_compile + ruff + suite 229 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

