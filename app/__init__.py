"""Claude Telegram Bot — application package (#302 restructure).

The previously flat top-level modules are grouped into subpackages:

  app.core      — engine, sessions, token_refresh, schedules (+ agent_context.md)
  app.storage   — db, archive, usage
  app.access    — access, allowlist, permissions, settings_schema
  app.telegram  — handlers, commands, streamer, rich_message, markup,
                  svg_image, table_image

with the bootstrap modules (bot, watchdog, config, i18n) at the package root.
Run with ``python -m app`` (see ``app/__main__.py``); the systemd unit
(``deploy/tg-bot.service``) does exactly that.
"""
from pathlib import Path

# Repo root = the directory CONTAINING this package (``app/..``). Modules now sit
# at varying depths in the package tree, so any module that needs a committed
# repo-root asset (the ``deploy/`` launcher scripts, etc.) resolves it from here
# instead of a brittle ``Path(__file__).parent`` that assumed a flat layout (#302).
REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"
