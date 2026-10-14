"""#435: the command registry must match the live handlers — the startup drift check
(`assert_commands_consistent`) used to fail silently inside setup_commands, leaving every
"/" menu stale. Running it here makes drift a test failure instead."""

from app import i18n
from app.telegram import commands


def test_registry_matches_live_handlers():
    commands.assert_commands_consistent(languages=tuple(i18n.LANGUAGES))
