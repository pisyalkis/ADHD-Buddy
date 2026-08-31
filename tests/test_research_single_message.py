import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_research_single_message.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [101000]
    def __init__(self, chat_id, text=None):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.text = text
        self.reply_calls = []

    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        self.reply_calls.append((text, kw.get("reply_markup")))
        return m


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=None, message=None, text_message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message) if data is not None else None
        self.message = text_message


class FakeBot:
    def __init__(self):
        self.sent = []
        self.deleted = []

    async def send_message(self, chat_id, text, **kw):
        m = FakeMsg(chat_id)
        self.sent.append((chat_id, text, m.message_id))
        return m

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


class FakeCtx:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Day 3: rating question -> tap -> open-text follow-up must replace the
    # SAME tracked message (not create a new one); typed answer clears it.
    # ══════════════════════════════════════════════════════════════════════
    app = FakeApp()
    await bot.send_research_question(app, uid, 3)
    rating_mid = bot._get_notif_msg_id(uid, "research")
    assert rating_mid is not None
    print("1. Day-3 rating question is tracked under channel 'research'")

    ctx = FakeCtx(app.bot)
    rating_screen = FakeMsg(chat_id=uid); rating_screen.message_id = rating_mid
    upd = FakeUpdate(uid, data="research_3_2", message=rating_screen)
    await bot.research_callback(upd, ctx)
    followup_mid = bot._get_notif_msg_id(uid, "research")
    assert (uid, rating_mid) in app.bot.deleted, \
        "answering the rating must delete it before showing the open-text follow-up"
    assert followup_mid is not None and followup_mid != rating_mid
    assert not rating_screen.reply_calls, \
        "the open-text follow-up must go through send_tracked_notification, not a plain reply"
    print("2. Tapping a rating replaces it with the open-text follow-up on the SAME channel")

    user_text = FakeMsg(chat_id=uid, text="Мне не хватало напоминаний")
    upd2 = FakeUpdate(uid, text_message=user_text)
    await bot.handle_text(upd2, ctx)
    assert (uid, followup_mid) in app.bot.deleted, \
        "typing the open-text answer must delete the tracked follow-up question"
    assert bot._get_notif_msg_id(uid, "research") is None
    print("3. Typing the open-text answer deletes the tracked follow-up and clears tracking")

    # ══════════════════════════════════════════════════════════════════════
    # Day 7: the "recorded" note + open question used to be TWO separate
    # messages -- must now be folded into one.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Аня', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    app2 = FakeApp()
    await bot.send_research_question(app2, uid2, 7)
    rating_mid2 = bot._get_notif_msg_id(uid2, "research")

    ctx2 = FakeCtx(app2.bot)
    rating_screen2 = FakeMsg(chat_id=uid2); rating_screen2.message_id = rating_mid2
    upd3 = FakeUpdate(uid2, data="research_7_yes", message=rating_screen2)
    await bot.research_callback(upd3, ctx2)
    assert not rating_screen2.reply_calls, \
        f"day 7 must not send two separate reply_text messages, got {rating_screen2.reply_calls}"
    combined_text = app2.bot.sent[-1][1]
    assert "Записал" in combined_text and "И ещё" in combined_text, combined_text
    print("4. Day 7's 'recorded' note and open question are now ONE message, not two")

    # ══════════════════════════════════════════════════════════════════════
    # Day 30: terminal branch -- no follow-up, tracked message is deleted
    # (not replaced) and the final "Спасибо" is a plain, untracked message.
    # ══════════════════════════════════════════════════════════════════════
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Игорь', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone="Asia/Tbilisi")
    app3 = FakeApp()
    await bot.send_research_question(app3, uid3, 30)
    rating_mid3 = bot._get_notif_msg_id(uid3, "research")

    ctx3 = FakeCtx(app3.bot)
    rating_screen3 = FakeMsg(chat_id=uid3); rating_screen3.message_id = rating_mid3
    upd4 = FakeUpdate(uid3, data="research_30_glad", message=rating_screen3)
    await bot.research_callback(upd4, ctx3)
    assert (uid3, rating_mid3) in app3.bot.deleted
    assert bot._get_notif_msg_id(uid3, "research") is None
    assert rating_screen3.reply_calls and "Спасибо" in rating_screen3.reply_calls[0][0]
    print("5. Day 30 (terminal) deletes the tracked rating message and sends a plain final thank-you")

    print("\nALL RESEARCH-SINGLE-MESSAGE TESTS PASSED")


asyncio.run(main())
