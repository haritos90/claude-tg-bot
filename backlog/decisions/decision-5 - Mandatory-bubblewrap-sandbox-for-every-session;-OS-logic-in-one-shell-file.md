---
id: decision-5
title: "Mandatory bubblewrap sandbox for every session; OS logic in one shell file"
date: '2026-07-04 00:00'
status: accepted
---
## Context

The `claude` CLI runs arbitrary tools; a code session can execute shell. Running it unconfined on the host is unacceptable, and a per-session opt-out is a footgun.

## Decision

EVERY session — chat AND code — runs its `claude` in a bubblewrap jail: unprivileged per-session uid, confined to its workdir, env wiped. There is NO per-session opt-out. All OS/sandbox interaction lives in ONE shell file, `deploy/sandbox-claude.sh` (not Python), so porting to another distro is a single-file change.

## Consequences

- An escape is unprivileged and cannot read other sessions' files.
- Chat is jailed too (it just carries no host-data tools and needs open egress for WebFetch).
- The global `SANDBOX_CODE` kill-switch stays for deployers but is always on here; the per-session toggle was retired.

**Source tasks:** #104, #180, #231, #312
