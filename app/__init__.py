"""Claude Telegram bot application package.

- `app.core`: engine, sessions, token refresh, schedules
- `app.storage`: db, archive, usage
- `app.access`: access, allowlist, permissions, settings schema
- `app.telegram`: handlers, commands, streamer, rendering
- Run with `python -m app`.
"""
from pathlib import Path

# Repo root, the directory containing this package.
# - Resolves committed assets like `deploy/` scripts
REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"
