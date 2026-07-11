---
id: TASK-194
title: "Credential broker had no inbound method/path allowlist"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 194
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Hardening: the credential broker now only forwards the exact request type the agent CLI needs and rejects anything else, so a stray local process can't borrow the subscription token to call other API endpoints.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`deploy/cred-broker.py` relayed ANY method/path to `api.anthropic.com` with the real OAuth bearer attached, so any process that reached `127.0.0.1:8789` could drive authenticated calls to arbitrary endpoints, not just `/v1/messages`. Added an inbound allowlist (`_ALLOW = (("POST","/v1/messages"),)`, prefix match, query ignored) checked at the very top of `_proxy` BEFORE the token is read or the upstream is contacted — a disallowed caller gets 403 and the bearer is never attached. Covers the only paths the CLI uses (`/v1/messages`, `/v1/messages/count_tokens`, `?beta=true`). Verified live: `GET /` → 403; unit-checked the matrix.
<!-- SECTION:NOTES:END -->

