import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_research_day30_open_question.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [201000]
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


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-09-02): day 30's research question is the
    # only one of the four (3/7/14/30) without an open-ended text follow-up
    # -- but it's the ONE day where the answer itself already triggers the
    # "LOW RATING, needs contact" admin alert (low_rating = value in
    # ("nope", "glad")). The most concerning churn signal in the whole bot
    # arrived with zero context. Add the open question, but ONLY for the
    # low-rating branch -- the good-signal answers (sad/meh) keep the
    # existing terminal "thanks" behavior unchanged.
    # ══════════════════════════════════════════════════════════════════════

    # 1. Low-rating answer ("nope" = "Всё равно") -> open question follow-up,
    #    same tracked message (not a new one), research_awaiting armed.
    uid = 1
    make_user(uid, "Артем")
    app = FakeApp()
    ctx = FakeCtx(app.bot)
    rating_msg = FakeMsg(uid)
    bot._set_notif_msg_id(uid, "research", rating_msg.message_id)
    upd = FakeUpdate(uid, data="research_30_nope", message=rating_msg)
    await bot.research_callback(upd, ctx)

    assert app.bot.sent, "a low-rating day-30 answer must trigger the open-question follow-up"
    _chat, followup_text, followup_mid = app.bot.sent[-1]
    assert bot.RESEARCH_OPEN_Q_DAY30_LOW in followup_text, followup_text
    assert bot.get_user(uid).get("research_awaiting") == f"30_open:{bot.RESEARCH_OPEN_Q_DAY30_LOW}", \
        bot.get_user(uid).get("research_awaiting")
    print("1. A low-rating day-30 answer ('nope') gets an open-question follow-up, research_awaiting armed")

    # 2. Actually answering that open question saves it (day30_text),
    #    end-to-end via handle_text's generic research_awaiting consumer.
    answer_msg = FakeMsg(uid, text="Если бы были напоминания вручную, а не по расписанию")
    upd2 = FakeUpdate(uid, text_message=answer_msg)
    await bot.handle_text(upd2, ctx)
    conn = sqlite3.connect(bot.DB_PATH)
    saved = conn.execute(
        "SELECT answer FROM research WHERE user_id=? AND question=?", (uid, "day30_text")
    ).fetchall()
    conn.close()
    assert any("напоминания вручную" in a for (a,) in saved), f"the day-30 open answer must be saved, got: {saved}"
    assert bot.get_user(uid).get("research_awaiting") in (0, "0", None), \
        "research_awaiting must be cleared after the open answer is saved"
    print("2. The open-text answer is saved end-to-end (day30_text), and research_awaiting is cleared")

    # 3. A GOOD-signal answer ("sad" = "Очень расстроюсь") keeps the
    #    existing terminal behavior -- no open question, no research_awaiting.
    uid2 = 2
    make_user(uid2, "Вика")
    app2 = FakeApp()
    ctx2 = FakeCtx(app2.bot)
    rating_msg2 = FakeMsg(uid2)
    bot._set_notif_msg_id(uid2, "research", rating_msg2.message_id)
    upd3 = FakeUpdate(uid2, data="research_30_sad", message=rating_msg2)
    await bot.research_callback(upd3, ctx2)

    assert not app2.bot.sent, "a good-signal day-30 answer must NOT get the open-question follow-up"
    assert rating_msg2.reply_calls, "sanity: the terminal 'thanks' message must still be sent"
    assert "Спасибо" in rating_msg2.reply_calls[0][0]
    assert bot.get_user(uid2).get("research_awaiting") in (0, "0", None, ""), \
        f"a good-signal answer must not arm research_awaiting, got: {bot.get_user(uid2).get('research_awaiting')}"
    print("3. A good-signal day-30 answer ('sad') keeps the existing terminal 'thanks' behavior, unchanged")

    print("\nALL RESEARCH-DAY30-OPEN-QUESTION TESTS PASSED")


asyncio.run(main())
