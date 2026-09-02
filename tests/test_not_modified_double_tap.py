import os, sys, asyncio, sqlite3
from telegram.error import BadRequest

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_not_modified_double_tap.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class NotModifiedMsg:
    """Simulates a message where edit_text always raises 'not modified',
    like a double-tap on an already-showing screen."""
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
        self.sent = []
    async def edit_text(self, text, **kw):
        raise BadRequest("Message is not modified")
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class RealErrorMsg:
    """Simulates a message where edit_text fails for a genuine reason
    (e.g. too old to edit) -- must still fall back to reply_text."""
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
        self.sent = []
    async def edit_text(self, text, **kw):
        raise BadRequest("Message to edit not found")
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
    async def answer(self, *a, **kw): pass


class FakeUpdate:
    def __init__(self, uid, data, message):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)
        self.callback_query = FakeQuery(uid, data, message)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Bug: _edit_msg_or_send treated a harmless double-tap ("Message is not
    # modified") the same as a real failure -- fell through to reply_text,
    # sending a duplicate message instead of a no-op.
    # ══════════════════════════════════════════════════════════════════════
    msg = NotModifiedMsg(uid)
    result = await bot._edit_msg_or_send(msg, "Тот же текст")
    assert result is msg, "a double-tap ('not modified') must be a no-op, not a new message"
    assert msg.sent == [], f"must NOT send a duplicate message on double-tap, got: {msg.sent}"
    print("1. _edit_msg_or_send treats 'not modified' as a no-op, no duplicate sent")

    # A genuine edit failure must still fall back to reply_text as before.
    msg2 = RealErrorMsg(uid)
    result2 = await bot._edit_msg_or_send(msg2, "Новый текст")
    assert msg2.sent, "a genuine edit failure must still fall back to reply_text"
    print("2. _edit_msg_or_send still falls back to reply_text on a genuine error")

    # ══════════════════════════════════════════════════════════════════════
    # Same bug class in _edit_tracked_msg -- used by handle_text retries
    # (e.g. re-entering the same invalid time format twice in a row).
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    ctx.user_data["settings_chat_id"] = uid
    ctx.user_data["settings_msg_id"] = 1

    class FakeBotNotModified:
        async def edit_message_text(self, chat_id, message_id, text, **kw):
            raise BadRequest("Message is not modified")
    ctx.bot = FakeBotNotModified()
    ok = await bot._edit_tracked_msg(ctx, "settings", "Тот же текст ошибки")
    assert ok is True, "a double-tap ('not modified') via _edit_tracked_msg must count as handled (True), not force a duplicate reply_text"
    print("3. _edit_tracked_msg treats 'not modified' as success (True), caller won't duplicate")

    class FakeBotRealError:
        async def edit_message_text(self, chat_id, message_id, text, **kw):
            raise BadRequest("Message to edit not found")
    ctx.bot = FakeBotRealError()
    ok2 = await bot._edit_tracked_msg(ctx, "settings", "Новый текст")
    assert ok2 is False, "a genuine edit failure must still return False so caller falls back"
    print("4. _edit_tracked_msg still returns False on a genuine error (caller falls back)")

    # ══════════════════════════════════════════════════════════════════════
    # day_card_nav / quickdisable_field_callback / dismiss_nudge_callback --
    # used to call q.message.edit_text directly, bypassing _edit_msg_or_send.
    # A fast double-tap (same callback_data twice before the client updates
    # its keyboard) now surfaces via on_error as a visible "something went
    # wrong" instead of being a silent no-op.
    # ══════════════════════════════════════════════════════════════════════
    today_iso = bot.datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    msg3 = NotModifiedMsg(uid)
    upd3 = FakeUpdate(uid, f"daycard_{today_iso}", msg3)
    await bot.day_card_nav(upd3, FakeCtx())
    assert msg3.sent == [], f"day_card_nav double-tap must be a no-op, not a duplicate message: {msg3.sent}"
    print("5. day_card_nav double-tap ('not modified') no longer sends a duplicate message")

    msg4 = NotModifiedMsg(uid)
    upd4 = FakeUpdate(uid, "dismiss_nudge", msg4)
    await bot.dismiss_nudge_callback(upd4, FakeCtx())
    assert msg4.sent == [], f"dismiss_nudge_callback double-tap must be a no-op: {msg4.sent}"
    print("6. dismiss_nudge_callback double-tap no longer sends a duplicate message")

    msg5 = NotModifiedMsg(uid)
    upd5 = FakeUpdate(uid, "quickdisable_writing", msg5)
    await bot.quickdisable_field_callback(upd5, FakeCtx())
    assert msg5.sent == [], f"quickdisable_field_callback double-tap must be a no-op: {msg5.sent}"
    print("7. quickdisable_field_callback double-tap no longer sends a duplicate message")

    print("\nALL NOT-MODIFIED-DOUBLE-TAP TESTS PASSED")


asyncio.run(main())
