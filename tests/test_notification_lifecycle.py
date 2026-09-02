import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_notification_lifecycle.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeChat:
    def __init__(self, uid): self.id = uid


class SentMsg:
    def __init__(self, mid, chat_id):
        self.message_id = mid
        self.chat_id = chat_id


class FakeBot:
    def __init__(self):
        self.sent = []
        self._next_id = 100
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        mid = self._next_id
        self._next_id += 1
        return SentMsg(mid, chat_id)
    async def delete_message(self, chat_id, message_id):
        pass


class FakeQueryMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return SentMsg(200, self.chat_id)


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid)
        self.message = FakeQueryMsg(uid)
        self.data = data
    async def answer(self, *a, **kw): pass


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeBot()


def has_scheduled_deletion(chat_id, message_id):
    conn = sqlite3.connect(bot.DB_PATH)
    row = conn.execute(
        "SELECT 1 FROM scheduled_deletions WHERE chat_id=? AND message_id=?", (chat_id, message_id)
    ).fetchone()
    conn.close()
    return row is not None


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    tz = bot.get_user_tz(bot.get_user(uid))
    now = datetime.now(tz)

    # ══════════════════════════════════════════════════════════════════════
    # Bug 1: focus_timer channel messages (the "already running" recap and
    # the "started" message) lacked ttl_seconds=0 -- rounds run 25-90 min,
    # far longer than the default 15-minute self-delete TTL.
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, focus_active=1, focus_end_time=(now + timedelta(minutes=20)).isoformat())
    ctx = FakeCtx()
    await bot.go_focus(FakeUpdate(uid), ctx)
    assert ctx.bot.sent, "go_focus must show the 'already running' recap"
    mid1 = ctx.bot._next_id - 1
    assert not has_scheduled_deletion(uid, mid1), \
        "the 'timer already running' recap must NOT self-delete (ttl_seconds=0) while the round is active"
    print("1. go_focus's 'already running' recap does not schedule a self-delete")

    bot.update_user(uid, focus_active=0, focus_end_time="")
    ctx2 = FakeCtx()
    upd2 = FakeUpdate(uid, data="focus_start_25")
    await bot.focus_start_callback(upd2, ctx2)
    assert ctx2.bot.sent, "focus_start_callback must send the 'started' message"
    mid2 = ctx2.bot._next_id - 1
    assert not has_scheduled_deletion(uid, mid2), \
        "the 'timer started' message must NOT self-delete (ttl_seconds=0) while the round is active"
    print("2. focus_start_callback's 'started' message does not schedule a self-delete")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 2: why_callback's explanation message had no TTL of its own --
    # only cleaned up by an explicit later response to the field/beacon it
    # explains. If the user opens the explanation but ignores the prompt
    # entirely, it stayed in the chat forever.
    # ══════════════════════════════════════════════════════════════════════
    ctx3 = FakeCtx()
    upd3 = FakeUpdate(uid, data="why_beacon_technique")
    await bot.why_callback(upd3, ctx3)
    mid3 = ctx3.user_data.get("why_msg_beacon_technique")
    assert mid3 is not None, "why_callback must track the explanation message id"
    assert has_scheduled_deletion(uid, mid3), \
        "the explanation message must have a self-delete safety net scheduled"
    print("3. why_callback schedules a self-delete safety net for the explanation")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 3: evening_notification didn't check for an active evening ritual
    # conversation, unlike morning_reminder (morning_conv_active) -- the
    # scheduled 21:00 nudge fired on top of an already-open ritual dialog.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Вика', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")

    class FakeConv:
        def __init__(self):
            self._conversations = {}

    fake_conv = FakeConv()
    fake_conv._conversations[(uid2, uid2)] = "some_state"
    bot._evening_conv = fake_conv
    fake_app = type("A", (), {"bot": FakeBot()})()
    try:
        result = await bot.evening_notification(fake_app, uid2)
        assert result is False, "must skip sending while the evening ritual is actively in progress"
        assert not fake_app.bot.sent, "must NOT send the 21:00 nudge on top of an open ritual dialog"
        print("4. evening_notification skips sending while the user's evening ritual is active")

        # Once the ritual conversation ends, the notification proceeds as before.
        fake_conv._conversations.clear()
        result2 = await bot.evening_notification(fake_app, uid2)
        assert result2 is True
        assert fake_app.bot.sent, "must send normally once no ritual conversation is active"
        print("5. evening_notification still sends normally once the ritual conversation ends")
    finally:
        bot._evening_conv = None

    # ══════════════════════════════════════════════════════════════════════
    # Bug 4: quick_toggle_beacon/quick_toggle_skill called the FULL
    # clear_awaiting_flags(ctx, update), which also cancels the active
    # morning/evening ConversationHandler -- these buttons live on the
    # pinned daily message, visible all day including during the ritual.
    # ══════════════════════════════════════════════════════════════════════
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Настя', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone="Asia/Tbilisi")

    fake_morning_conv = FakeConv()
    fake_morning_conv._conversations[(uid3, uid3)] = "morning_state"
    bot._morning_conv = fake_morning_conv
    try:
        ctx4 = FakeCtx()
        await bot.quick_toggle_beacon(FakeUpdate(uid3), ctx4)
        assert (uid3, uid3) in fake_morning_conv._conversations, \
            "quick_toggle_beacon must NOT cancel an active morning ritual conversation"
        print("6. quick_toggle_beacon no longer cancels an active morning/evening ritual conversation")

        ctx5 = FakeCtx()
        await bot.quick_toggle_skill(FakeUpdate(uid3), ctx5)
        assert (uid3, uid3) in fake_morning_conv._conversations, \
            "quick_toggle_skill must NOT cancel an active morning ritual conversation"
        print("7. quick_toggle_skill no longer cancels an active morning/evening ritual conversation")
    finally:
        bot._morning_conv = None

    # ══════════════════════════════════════════════════════════════════════
    # Bug 5: handle_edit_reminder_intent / handle_delete_pool_intent fell
    # back to arbitrary candidates on ZERO matches, using the SAME prompt
    # text as a real "found similar" match -- misleading.
    # ══════════════════════════════════════════════════════════════════════
    uid4 = 4
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (4, 'Олег', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid4, timezone="Asia/Tbilisi")
    remind_key = (datetime.now(bot.get_user_tz(bot.get_user(uid4))) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    bot.add_reminder(uid4, "Позвонить маме", remind_key)

    msg4 = FakeQueryMsg(uid4)
    await bot.handle_edit_reminder_intent(msg4, FakeCtx(), uid4, "полить цветы")  # no match at all
    assert msg4.sent, "must reply"
    assert "не нашёл" in msg4.sent[-1][0].lower(), \
        f"zero matches must be worded honestly as 'not found', got: {msg4.sent[-1][0]!r}"
    print("8. handle_edit_reminder_intent honestly says 'not found' on zero matches")

    bot.add_pool_task(uid4, "Купить хлеб")
    msg5 = FakeQueryMsg(uid4)
    await bot.handle_delete_pool_intent(msg5, uid4, "постирать шторы")  # no match at all
    assert msg5.sent, "must reply"
    assert "не нашёл" in msg5.sent[-1][0].lower(), \
        f"zero matches must be worded honestly as 'not found', got: {msg5.sent[-1][0]!r}"
    print("9. handle_delete_pool_intent honestly says 'not found' on zero matches")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 6: day 7/30 research low_rating never triggered -- non-numeric
    # callback values compared against numeric strings.
    # ══════════════════════════════════════════════════════════════════════
    uid5 = 999  # matches NOTIFY_USER_ID so the alert path itself doesn't error
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (999, 'Админ', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid5, timezone="Asia/Tbilisi")

    class FakeAdminBot:
        def __init__(self):
            self.sent = []
        async def send_message(self, chat_id, text, **kw):
            self.sent.append(text)

    upd7 = FakeUpdate(uid5, data="research_7_no")
    upd7.callback_query.message.bot = FakeAdminBot()
    await bot.research_callback(upd7, FakeCtx())
    assert any("НИЗКАЯ ОЦЕНКА" in t for t in upd7.callback_query.message.bot.sent), \
        "day 7's worst answer ('no') must trigger the low-rating admin alert"
    print("10. day 7's worst answer ('no') now triggers the low-rating alert")

    upd30 = FakeUpdate(uid5, data="research_30_nope")
    upd30.callback_query.message.bot = FakeAdminBot()
    await bot.research_callback(upd30, FakeCtx())
    assert any("НИЗКАЯ ОЦЕНКА" in t for t in upd30.callback_query.message.bot.sent), \
        "day 30's worst answer ('nope') must trigger the low-rating admin alert"
    print("11. day 30's worst answer ('nope') now triggers the low-rating alert")

    print("\nALL NOTIFICATION-LIFECYCLE TESTS PASSED")


asyncio.run(main())
