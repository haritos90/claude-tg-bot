<!-- Keep everything in this PR — title, description, comments, code — in English (see CONTRIBUTING.md). -->

## What & why

<!-- What does this change and why? Link the TODO.md task it closes, e.g. #64. -->

## Type

<!-- Conventional Commits type: feat | fix | docs | refactor | test | build | chore -->

## Checklist

- [ ] PR title follows Conventional Commits (`type(scope): summary`).
- [ ] `python -m py_compile *.py`, the import smoke (AGENTS.md §3), and `pytest -q` are green.
- [ ] User-facing strings go through `i18n` (`en` **and** `ru`), not hardcoded.
- [ ] No `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` introduced (subscription-only).
- [ ] `setting_sources=[]` preserved on every `ClaudeAgentOptions`.
- [ ] `TODO.md` updated (task moved to **Closed** with a **Resolution**).

## Notes for reviewers

<!-- Anything worth calling out: trade-offs, follow-ups, manual testing done, areas to focus review on. -->
