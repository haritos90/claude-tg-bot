---
id: TASK-193
title: "Credential broker relayed an empty body for chunked requests"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 193
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Hardening: the credential broker now handles a chunked request body instead of silently forwarding nothing, so a turn can't fail in a hard-to-diagnose way if the client streams its request.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`deploy/cred-broker.py` read the inbound body only when `content-length` was present, and `_DROP_REQ` strips `transfer-encoding` — so a `Transfer-Encoding: chunked` request body (no Content-Length) would have been forwarded EMPTY and the turn failed silently (it worked only because the CLI sends Content-Length). Added `_read_request_body`: when the request is chunked it de-chunks `self.rfile` (size lines, per-chunk CRLF, terminating 0-chunk + trailers) into a buffer; otherwise it reads Content-Length bytes. http.client then re-frames the buffered body with a Content-Length upstream. Verified: chunked / Content-Length / empty all read correctly.
<!-- SECTION:NOTES:END -->

