"""#434: the MAX transport — id namespace, HTML conversion, the aiogram-session translator
(with the no-streaming "Thinking…" placeholder), call routing, update conversion, and the
owner-routed permission prompt."""

from __future__ import annotations

import asyncio

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, GetMe, SendMessage, SetMyCommands
from aiogram.types import (BotCommand, BufferedInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup)

from app.access.permissions import PermissionGate
from app.max import html as mhtml
from app.max.bridge import MaxSession, RoutingSession
from app.max.client import MaxApiError
from app.max.ids import (MAX_ID_OFFSET, FileRegistry, MidRegistry, is_internal_max,
                         to_internal, to_max)
from app.max.poller import MaxPoller
from app.telegram.rich_message import SendRichMessage, SendRichMessageDraft


# ----------------------------------------------------------------------------- fakes
class FakeApi:
    def __init__(self):
        self.calls: list[tuple] = []
        self.n = 0
        self.fail_html_once = False

    async def send_message(self, *, user_id=None, chat_id=None, body, disable_link_preview=None):
        if self.fail_html_once and body.get("format") == "html":
            self.fail_html_once = False
            raise MaxApiError(400, "bad.markup", "nope", "POST /messages")
        self.n += 1
        self.calls.append(("send", user_id, body))
        return {"body": {"mid": f"mid.{self.n}"}}

    async def edit_message(self, mid, body):
        self.calls.append(("edit", mid, body))

    async def delete_message(self, mid):
        self.calls.append(("delete", mid))

    async def answer_callback(self, callback_id, *, notification=None, message=None):
        self.calls.append(("answer", callback_id, notification))

    async def upload(self, kind, data, filename):
        self.calls.append(("upload", kind, len(data), filename))
        return f"tok-{kind}"

    async def download(self, url, chunk_size=65536):
        self.calls.append(("download", url))
        yield b"OggS-voice-"
        yield b"bytes"

    async def patch_commands(self, commands):
        self.calls.append(("commands", commands))

    async def send_action(self, chat_id, action="typing_on"):
        self.calls.append(("action", chat_id, action))

    async def get_me(self):
        return {"user_id": 42, "first_name": "Bot", "username": "bot_max", "is_bot": True}

    async def close(self):
        pass

    def kinds(self):
        return [c[0] for c in self.calls]


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.methods = []

    async def make_request(self, bot, method, timeout=None):
        self.methods.append(method.__api_method__)
        return True

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536,
                             raise_for_status=True):
        yield b""

    async def close(self):
        pass


def _bot(session):
    return Bot(token="123456:ABCDEFghijkl", session=session,
               default=DefaultBotProperties(parse_mode="HTML"))


def _rig(fail_html_once: bool = False):
    """(FakeApi, MaxSession, Bot) wired together."""
    api = FakeApi()
    api.fail_html_once = fail_html_once
    ms = MaxSession(api)
    return api, ms, _bot(ms)


UID = to_internal(777)


# ----------------------------------------------------------------------------- ids
def test_id_namespace_round_trip():
    assert to_internal(5) == MAX_ID_OFFSET + 5
    assert is_internal_max(to_internal(5)) and not is_internal_max(2859339)
    assert not is_internal_max(-100123) and not is_internal_max(None)
    assert to_max(to_internal(335910883)) == 335910883


def test_mid_registry_is_stable_and_reversible():
    r = MidRegistry()
    a = r.int_of("mid.a")
    assert r.int_of("mid.a") == a and r.mid_of(a) == "mid.a"
    assert r.int_of("mid.b") == a + 1 and r.mid_of(999) is None


def test_file_registry_path_round_trip():
    f = FileRegistry()
    fid = f.register("https://cdn/x.pdf", "x.pdf", 10, "application/pdf")
    assert FileRegistry.is_max(fid) and not FileRegistry.is_max("AgAD")
    path = FileRegistry.path_of(fid)
    assert f.by_path(f"https://api.telegram.org/file/bot1:x/{path}").url == "https://cdn/x.pdf"


# ----------------------------------------------------------------------------- html
def test_tg_html_to_max_drops_what_max_lacks():
    src = ('<b>a</b> <tg-spoiler>s</tg-spoiler> <blockquote expandable>q</blockquote> '
           '<pre><code class="language-py">x = 1</code></pre> <tg-emoji emoji-id="5">🙂</tg-emoji>'
           ' <span class="tg-spoiler">z</span> <strike>o</strike>')
    out = mhtml.tg_html_to_max(src)
    assert out == '<b>a</b> s <blockquote>q</blockquote> <pre>x = 1</pre> 🙂 z <s>o</s>'
    assert mhtml.strip_tags("<b>&lt;x&gt;</b>") == "<x>"


def test_split_html_respects_max_limit():
    parts = mhtml.split_html("line\n" * 2000)
    assert len(parts) > 1 and all(len(p) <= mhtml.SAFE_LIMIT for p in parts)
    assert mhtml.split_html("short") == ["short"]


def test_keyboard_to_max_maps_callback_and_url_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Allow", callback_data="perm:1:allow"),
         InlineKeyboardButton(text="Docs", url="https://example.com")]])
    out = mhtml.keyboard_to_max(kb)
    assert out["type"] == "inline_keyboard"
    assert out["payload"]["buttons"] == [[
        {"type": "callback", "text": "Allow", "payload": "perm:1:allow"},
        {"type": "link", "text": "Docs", "url": "https://example.com"}]]
    assert mhtml.keyboard_to_max(None) is None


# ----------------------------------------------------------------------------- bridge
def test_send_message_translates_to_post_with_html():
    api, ms, bot = _rig()

    async def go():
        return await bot.send_message(UID, "<b>hi</b> <tg-spoiler>x</tg-spoiler>")
    sent = asyncio.run(go())
    kind, user_id, body = api.calls[0]
    assert (kind, user_id) == ("send", 777)
    assert body["text"] == "<b>hi</b> x" and body["format"] == "html"
    assert sent.chat.id == UID and ms.mids.mid_of(sent.message_id) == "mid.1"


def test_thinking_placeholder_is_replaced_by_the_final_reply():
    api, ms, bot = _rig()

    async def go():
        ph = "<tg-thinking>Opus 5.5 · medium<br>Thinking…</tg-thinking>"
        await bot(SendRichMessageDraft(chat_id=UID, draft_id=1, rich_message={"html": ph}))
        await bot(SendRichMessageDraft(chat_id=UID, draft_id=1, rich_message={"markdown": "partial"}))
        await bot(SendRichMessageDraft(chat_id=UID, draft_id=1, rich_message={"markdown": "partial more"}))
        final = await bot(SendRichMessage(chat_id=UID, rich_message={"markdown": "**done**"}))
        again = await bot.send_message(UID, "next")
        return final, again
    final, again = asyncio.run(go())
    assert api.kinds() == ["send", "edit", "send"], api.calls
    first = api.calls[0][2]
    assert first["text"] == "💭 Opus 5.5 · medium\nThinking…" and first.get("notify") is False
    kind, mid, body = api.calls[1]
    assert mid == "mid.1" and body["text"] == "<b>done</b>" and body["format"] == "html"
    assert ms.mids.mid_of(final.message_id) == "mid.1"
    assert ms.mids.mid_of(again.message_id) == "mid.2"


def test_empty_draft_clears_the_placeholder():
    api, ms, bot = _rig()

    async def go():
        await bot(SendRichMessageDraft(chat_id=UID, draft_id=1, rich_message={"html": "<tg-thinking>T</tg-thinking>"}))
        await bot(SendRichMessageDraft(chat_id=UID, draft_id=1, rich_message={"html": ""}))
    asyncio.run(go())
    assert api.kinds() == ["send", "delete"] and api.calls[1][1] == "mid.1"


def test_edit_delete_and_callback_answer():
    api, ms, bot = _rig()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="x", callback_data="a")]])

    async def go():
        m = await bot.send_message(UID, "one", reply_markup=kb)
        await bot.edit_message_text("two", chat_id=UID, message_id=m.message_id)
        await bot.edit_message_reply_markup(chat_id=UID, message_id=m.message_id, reply_markup=kb)
        await bot(AnswerCallbackQuery(callback_query_id="max:cb-1", text="ok"))
        await bot.delete_message(UID, m.message_id)
    asyncio.run(go())
    kinds = api.kinds()
    assert kinds == ["send", "edit", "edit", "answer", "delete"]
    assert api.calls[0][2]["attachments"][0]["type"] == "inline_keyboard"
    assert api.calls[1][2] == {"text": "two", "format": "html", "attachments": []}   # edit drops kb
    assert api.calls[2][2]["text"] == "two" and api.calls[2][2]["attachments"][0]["type"] == "inline_keyboard"
    assert api.calls[3][1:] == ("cb-1", "ok")
    assert api.calls[4][1] == "mid.1"


def test_document_upload_and_placeholder_not_edited_for_media():
    api, ms, bot = _rig()

    async def go():
        await bot(SendRichMessageDraft(chat_id=UID, draft_id=1, rich_message={"html": "<tg-thinking>T</tg-thinking>"}))
        await bot.send_document(UID, BufferedInputFile(b"abc", filename="r.md"), caption="cap")
    asyncio.run(go())
    assert api.kinds() == ["send", "upload", "delete", "send"]
    assert api.calls[1][1:] == ("file", 3, "r.md")
    body = api.calls[3][2]
    assert body["attachments"] == [{"type": "file", "payload": {"token": "tok-file"}}]
    assert body["text"] == "cap"


def test_unsupported_method_raises_bad_request():
    api, ms, bot = _rig()
    with pytest.raises(TelegramBadRequest):
        asyncio.run(bot.pin_chat_message(UID, 1))
    assert api.calls == []


def test_set_commands_only_default_scope_and_capped():
    api, ms, bot = _rig()
    cmds = [BotCommand(command=f"c{i}", description=f"d{i}") for i in range(40)]

    async def go():
        await bot(SetMyCommands(commands=cmds))
        await bot(SetMyCommands(commands=cmds, language_code="ru"))
    asyncio.run(go())
    # MAX has one global list: the default-scope call registers the shared menu from the
    # command registry (not the caller's trio), owner commands excluded, ≤32.
    from app.telegram import commands
    assert api.kinds() == ["commands"]
    names = [c["name"] for c in api.calls[0][1]]
    assert names[:3] == ["new", "sessions", "settings"] and len(names) <= 32
    assert set(names) == {s for s in commands.menu_slugs() if commands.by_slug()[s].scope != "owner"}
    assert all(c["description"] for c in api.calls[0][1])


def test_rejected_html_falls_back_to_plain_text():
    api, ms, bot = _rig(fail_html_once=True)
    asyncio.run(bot.send_message(UID, "<b>bold</b>"))
    assert api.kinds() == ["send"] and api.calls[0][2]["text"] == "bold" and api.calls[0][2]["format"] is None


def test_get_me_maps_bot_identity():
    api, ms, bot = _rig()
    me = asyncio.run(bot(GetMe()))
    assert me.id == to_internal(42) and me.username == "bot_max" and ms.bot_user["user_id"] == 42


# ----------------------------------------------------------------------------- routing
def test_routing_session_picks_platform_by_address():
    tg = RecordingSession()
    api = FakeApi()
    ms = MaxSession(api)
    rs = RoutingSession(tg, ms)
    bot = _bot(rs)

    async def go():
        await bot.send_message(2859339, "tg user")
        await bot.send_message(UID, "max user")
        await bot(AnswerCallbackQuery(callback_query_id="max:z"))
        await bot(AnswerCallbackQuery(callback_query_id="123"))
        await bot(SetMyCommands(commands=[BotCommand(command="help", description="h")]))
        await bot(GetMe())
    asyncio.run(go())
    assert tg.methods == ["sendMessage", "answerCallbackQuery", "setMyCommands", "getMe"]
    assert api.kinds() == ["send", "answer", "commands"]
    assert RoutingSession(tg, None).route(SendMessage(chat_id=UID, text="x")) == "tg"


# ----------------------------------------------------------------------------- poller
def _poller():
    api = FakeApi()
    ms = MaxSession(api)
    return MaxPoller(api, ms, dp=None, bot=None), ms


def test_message_created_text_becomes_private_message():
    p, ms = _poller()
    upd = {"update_type": "message_created", "timestamp": 1700000000000, "user_locale": "ru-RU",
           "message": {"sender": {"user_id": 777, "first_name": "Ann", "username": "ann", "is_bot": False},
                       "recipient": {"chat_id": 555, "chat_type": "dialog", "user_id": 777},
                       "timestamp": 1700000000000,
                       "body": {"mid": "mid.x", "seq": 1, "text": "/status"}}}
    out = p.to_updates(upd)
    assert len(out) == 1
    m = out[0]["message"]
    assert m["chat"] == {"id": UID, "type": "private", "first_name": "Ann", "last_name": None, "username": "ann"}
    assert m["from"]["id"] == UID and m["from"]["language_code"] == "ru-RU" and m["text"] == "/status"
    assert m["date"] == 1700000000 and ms.mids.mid_of(m["message_id"]) == "mid.x"
    assert ms.chat_of_user[UID] == 555


def test_message_created_attachments_map_to_photo_document_voice():
    p, ms = _poller()
    base = {"sender": {"user_id": 777, "first_name": "A", "is_bot": False},
            "recipient": {"chat_id": 1, "chat_type": "dialog"}}
    two = p.to_updates({"update_type": "message_created", "message": {
        **base, "body": {"mid": "m1", "seq": 1, "text": "look", "attachments": [
            {"type": "image", "payload": {"photo_id": 1, "token": "t1", "url": "https://i/1"}},
            {"type": "image", "payload": {"photo_id": 2, "token": "t2", "url": "https://i/2"}}]}}})
    assert len(two) == 2 and all("photo" in u["message"] for u in two)
    assert two[0]["message"]["caption"] == "look" and "caption" not in two[1]["message"]
    assert two[0]["message"]["media_group_id"] == two[1]["message"]["media_group_id"]
    assert ms.files.get(two[0]["message"]["photo"][0]["file_id"]).url == "https://i/1"

    doc = p.to_updates({"update_type": "message_created", "message": {
        **base, "body": {"mid": "m2", "seq": 2, "text": None, "attachments": [
            {"type": "file", "filename": "r.pdf", "size": 9, "payload": {"url": "https://f/r", "token": "ft"}}]}}})
    d = doc[0]["message"]["document"]
    assert d["file_name"] == "r.pdf" and d["mime_type"] == "application/pdf" and d["file_size"] == 9

    voice = p.to_updates({"update_type": "message_created", "message": {
        **base, "body": {"mid": "m3", "seq": 3, "attachments": [
            {"type": "audio", "payload": {"url": "https://a/1", "token": "at"}}]}}})
    assert voice[0]["message"]["voice"]["duration"] == 0

    loc = p.to_updates({"update_type": "message_created", "message": {
        **base, "body": {"mid": "m4", "seq": 4, "attachments": [
            {"type": "location", "latitude": 55.75, "longitude": 37.62}]}}})
    assert loc[0]["message"]["location"] == {"latitude": 55.75, "longitude": 37.62}


def test_voice_message_bytes_download_through_the_routing_session():
    """A MAX voice note reaches the shared voice handler as bytes."""
    from aiogram.types import Voice
    p, ms = _poller()
    upd = p.to_updates({"update_type": "message_created", "message": {
        "sender": {"user_id": 777, "first_name": "A", "is_bot": False},
        "recipient": {"chat_id": 1, "chat_type": "dialog"},
        "body": {"mid": "m5", "seq": 5, "attachments": [
            {"type": "audio", "payload": {"url": "https://cdn.max/voice.m4a", "token": "vt"},
             "transcription": "hello"}]}}})
    v = upd[0]["message"]["voice"]
    bot = _bot(RoutingSession(RecordingSession(), ms))
    buf = asyncio.run(bot.download(Voice(file_id=v["file_id"], file_unique_id=v["file_id"],
                                         duration=0)))
    assert buf.read() == b"OggS-voice-bytes"
    assert ("download", "https://cdn.max/voice.m4a") in ms.api.calls


def test_rich_map_block_is_refused_so_the_reply_interleaves():
    """No rich blocks on MAX: a map in a rich message is refused; pins go as locations."""
    api, ms, bot = _rig()
    md = 'Here:\n\n<tg-map lat="55.750000" long="37.620000" zoom="15"/>\n\nenjoy'
    with pytest.raises(TelegramBadRequest):
        asyncio.run(bot(SendRichMessage(chat_id=UID, rich_message={"markdown": md})))
    assert api.calls == []
    routing = RoutingSession(RecordingSession(), ms)
    assert routing.embeds_rich_media(UID) is False
    assert routing.embeds_rich_media(2859339) is True
    assert RoutingSession(RecordingSession(), None).embeds_rich_media(UID) is True
    asyncio.run(bot.send_location(chat_id=UID, latitude=55.75, longitude=37.62))
    sent = [c for c in api.calls if c[0] == "send"][-1][2]
    assert sent["attachments"] == [{"type": "location", "latitude": 55.75, "longitude": 37.62}]


def test_group_chat_bots_and_empty_messages_are_ignored():
    p, _ = _poller()
    grp = {"update_type": "message_created", "message": {
        "sender": {"user_id": 1, "first_name": "x", "is_bot": False},
        "recipient": {"chat_id": 9, "chat_type": "chat"}, "body": {"mid": "m", "seq": 1, "text": "hi"}}}
    assert p.to_updates(grp) == []
    frombot = {"update_type": "message_created", "message": {
        "sender": {"user_id": 1, "first_name": "x", "is_bot": True},
        "recipient": {"chat_type": "dialog"}, "body": {"mid": "m", "seq": 1, "text": "hi"}}}
    assert p.to_updates(frombot) == []
    sticker = {"update_type": "message_created", "message": {
        "sender": {"user_id": 1, "first_name": "x", "is_bot": False},
        "recipient": {"chat_type": "dialog"}, "body": {"mid": "m", "seq": 1, "attachments": [{"type": "sticker"}]}}}
    assert p.to_updates(sticker) == []
    assert p.to_updates({"update_type": "dialog_muted"}) == []


def test_callback_and_bot_started_conversion():
    p, ms = _poller()
    ms.bot_user = {"user_id": 42, "first_name": "Bot", "username": "bot_max"}
    cb = p.to_updates({"update_type": "message_callback", "timestamp": 1700000000000,
                       "callback": {"callback_id": "c9", "payload": "ses:sw:-3", "timestamp": 1,
                                    "user": {"user_id": 777, "first_name": "Ann", "is_bot": False}},
                       "message": {"recipient": {"chat_id": 555, "chat_type": "dialog"},
                                   "body": {"mid": "mid.k", "seq": 2, "text": "menu"}}})
    q = cb[0]["callback_query"]
    assert q["id"] == "max:c9" and q["data"] == "ses:sw:-3" and q["from"]["id"] == UID
    assert q["message"]["text"] == "menu" and q["message"]["from"]["id"] == to_internal(42)
    assert ms.mids.mid_of(q["message"]["message_id"]) == "mid.k"

    st = p.to_updates({"update_type": "bot_started", "chat_id": 555, "user_locale": "en",
                       "user": {"user_id": 777, "first_name": "Ann", "is_bot": False}})
    assert st[0]["message"]["text"] == "/start" and st[0]["message"]["entities"][0]["type"] == "bot_command"


def test_updates_validate_as_aiogram_objects():
    from aiogram.types import Update
    p, _ = _poller()
    data = p.to_updates({"update_type": "message_created", "message": {
        "sender": {"user_id": 777, "first_name": "A", "is_bot": False},
        "recipient": {"chat_type": "dialog"}, "body": {"mid": "m", "seq": 1, "text": "hi"}}})[0]
    u = Update.model_validate(data)
    assert u.message.chat.type == "private" and u.message.from_user.id == UID


# ----------------------------------------------------------------------------- gate
def test_permission_prompt_goes_to_owner_for_foreign_session():
    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, **kw):
            self.sent.append((chat_id, text, kw))

            class M:
                message_id = 7
            return M()

        async def edit_message_text(self, *a, **kw):
            pass

    fb = FakeBot()
    gate = PermissionGate(fb, owner_id=2859339)
    cb = gate.make_callback(UID, None, -5, "default", cwd=None)

    async def go():
        task = asyncio.create_task(cb("Bash", {"command": "rm -rf /tmp/x"}, None))
        for _ in range(50):
            await asyncio.sleep(0.01)
            if fb.sent:
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
    chat_id, text, kw = fb.sent[0]
    assert chat_id == 2859339 and str(UID) in text and "message_thread_id" not in kw
