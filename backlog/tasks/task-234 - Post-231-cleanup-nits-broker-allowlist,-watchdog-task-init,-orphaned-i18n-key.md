---
id: TASK-234
title: "Post-#231 cleanup nits: broker allowlist, watchdog task init, orphaned i18n key"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 234
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Hardening + tidy: the credential broker's path allowlist now rejects look-alike paths, the watchdog task can't leak on a startup error, and the stale `/sandbox` toggle strings are gone from the catalog.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Three cleanups from the #231 review. (1) `deploy/cred-broker.py` `_path_allowed` matched the inbound allowlist by bare prefix (`base.startswith("/v1/messages")`), so a sibling like `/v1/messages_evil` also passed; tightened to `base == p or base.startswith(p + "/")` so only `/v1/messages` and `/v1/messages/...` (e.g. `/v1/messages/count_tokens`) match. Added `test_cred_broker_path_allowlist` in `tests/test_sandbox_119.py`. (2) `bot.py` watchdog task: it was created outside the try whose finally cancels it (a raise during sandbox setup could leak it). Moved the `asyncio.create_task(watchdog.run(...))` to the first statement inside the try, keeping `watchdog.ready()` before the sandbox setup (the #158/#196 invariant — READY must precede local setup) and the pre-try `wd_task = None` as the finally's guard; updated the seccomp comment that referenced the (formerly) already-running task. (3) `i18n.py`: commented out the orphaned `sandbox.show` / `sandbox.show_scoped` / `sandbox.set_on` / `sandbox.set_off` keys that still advertised the `/sandbox on | off` toggle retired in #231 (no live `.py` callers; `sandbox.mandatory` is the live key), tagged `#234` per the comment-out-with-task-ref rule. py_compile + import + pytest (155 passed, 1 pre-existing unrelated PIL font failure) + ruff clean; live restart confirmed "Run polling" with the watchdog probing post-setup as intended.
<!-- SECTION:NOTES:END -->

