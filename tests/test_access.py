"""Tests for the allowlist middleware: drop unknown, notify owner.

- owner gets an access-request notice to grant by id
"""

import asyncio
from types import SimpleNamespace

from app.access.access import AllowlistMiddleware

OWNER = 1


class _FakeAllow:
    def __init__(self, allowed):
        self._allowed = allowed

    def is_allowed(self, uid, uname):
        return uid in self._allowed

    def pin(self, uid, uname):
        pass


class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw))


def _msg(uid, text="hi", bot=None):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=uid, username="bob", first_name="Bob", last_name=None),
        text=text, bot=bot,
    )


async def _noop_handler(event, data):
    return "HANDLED"


def test_unknown_user_dropped_and_owner_notified_once():
    async def _run():
        bot = _FakeBot()
        mw = AllowlistMiddleware(_FakeAllow({OWNER}), owner_id=OWNER)
        # Unknown user typing: dropped, owner pinged.
        res = await mw(_noop_handler, _msg(2, bot=bot), {})
        assert res is None                         # update dropped
        assert len(bot.sent) == 1
        chat_id, text, kw = bot.sent[0]
        assert chat_id == OWNER and "2" in text    # id shown to the owner
        assert "req:al:2" in str(kw) and "req:ac:2" in str(kw)   # one-tap grant buttons
        # A second attempt in the window does not re-notify.
        await mw(_noop_handler, _msg(2, bot=bot), {})
        assert len(bot.sent) == 1
    asyncio.run(_run())


def test_allowed_user_passes_through_no_notice():
    async def _run():
        bot = _FakeBot()
        mw = AllowlistMiddleware(_FakeAllow({OWNER, 2}), owner_id=OWNER)
        res = await mw(_noop_handler, _msg(2, bot=bot), {})
        assert res == "HANDLED"                     # downstream handler ran
        assert bot.sent == []                        # no access-request notice
    asyncio.run(_run())


def test_owner_never_notifies_self():
    async def _run():
        bot = _FakeBot()
        mw = AllowlistMiddleware(_FakeAllow(set()), owner_id=OWNER)  # owner not in fake set
        # Owner never notifies itself, even if not allowlisted.
        await mw(_noop_handler, _msg(OWNER, bot=bot), {})
        assert bot.sent == []
    asyncio.run(_run())
