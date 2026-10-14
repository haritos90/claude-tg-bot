"""The command registry must match the live handlers.

- the startup drift check used to fail silently
- running it here makes drift a test failure
"""

from app import i18n
from app.telegram import commands


def test_registry_matches_live_handlers():
    commands.assert_commands_consistent(languages=tuple(i18n.LANGUAGES))
