"""#328: maintenance-mode gate — while the sentinel exists the bot replies a stub and drops the
update (no handler runs → no new session/turn data), so a migration sees a frozen dataset."""

import asyncio
from types import SimpleNamespace

from app.access import access
from app.access.access import AllowlistMiddleware


class _Allow:
    def is_allowed(self, uid, uname):
        return True

    def pin(self, uid, uname):
        pass


class _Msg:
    """Duck-typed Message (no `.data` → treated as a message, not a callback)."""

    def __init__(self):
        self.from_user = SimpleNamespace(id=1, username="u")
        self.text = "hi"
        self.replies = []

    async def answer(self, text, **kw):
        self.replies.append(text)


def test_maintenance_drops_update_and_replies_stub(monkeypatch, tmp_path):
    sentinel = tmp_path / "MAINT"
    monkeypatch.setattr(access, "_MAINTENANCE_SENTINEL", str(sentinel))
    mw = AllowlistMiddleware(_Allow())
    handled = []

    async def handler(event, data):
        handled.append(event)
        return "ran"

    async def scenario():
        msg = _Msg()
        # maintenance ON → drop + stub, handler NEVER runs (no data created)
        sentinel.write_text("")
        assert access.maintenance_active() is True
        result = await mw(handler, msg, {})
        assert result is None
        assert handled == []
        assert msg.replies and "🛠" in msg.replies[0]
        # maintenance OFF → handler runs normally
        sentinel.unlink()
        assert access.maintenance_active() is False
        msg2 = _Msg()
        assert await mw(handler, msg2, {}) == "ran"
        assert handled == [msg2] and msg2.replies == []

    asyncio.run(scenario())
