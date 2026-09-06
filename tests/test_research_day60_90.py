import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_research_day60_90.db")
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

    def __init__(self, chat_id, text=None, bot=None):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.text = text
        self.reply_calls = []
        self.bot = bot

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
    def __init__(self, uid, data=None, message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message) if data is not None else None
        self.message = None


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


def make_user(uid, name, gender="M"):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, ?)", (uid, name, gender))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-09-03): the research program terminated at
    # day 30 -- no follow-up points once the trial and first month are long
    # over, exactly when real long-term retention/churn becomes visible.
    # Added day 60 (always-ask open follow-up, like 3/7/14) and day 90
    # (terminal, open follow-up only on the risky answer, like 30).
    # ══════════════════════════════════════════════════════════════════════

    # 1. RESEARCH_MILESTONES now includes 60 and 90.
    assert 60 in bot.RESEARCH_MILESTONES and 90 in bot.RESEARCH_MILESTONES, bot.RESEARCH_MILESTONES
    print("1. RESEARCH_MILESTONES includes the new day 60 and day 90 checkpoints")

    # ══════════════════════════════════════════════════════════════════════
    # Day 60: always has an open follow-up, regardless of which button was
    # tapped -- same principle as days 3/7/14 (RESEARCH_TEXT_FOLLOWUP_DAYS).
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем", "M")
    app = FakeApp()
    await bot.send_research_question(app, uid, 60)
    rating_mid = bot._get_notif_msg_id(uid, "research")
    assert rating_mid is not None
    assert str(60) in (bot.get_user(uid).get("research_done") or "").split(",")
    print("2. Day 60's rating question is sent and marked as done")

    ctx = FakeCtx(app.bot)
    rating_screen = FakeMsg(chat_id=uid, bot=app.bot); rating_screen.message_id = rating_mid
    upd = FakeUpdate(uid, data="research_60_no_change", message=rating_screen)
    await bot.research_callback(upd, ctx)
    assert not rating_screen.reply_calls, \
        "day 60 must fold 'recorded' + open question into ONE tracked message, not a plain reply"
    combined_text = app.bot.sent[-1][1]
    assert "Записал" in combined_text and "И ещё" in combined_text, combined_text
    assert bot.get_user(uid).get("research_awaiting", "").startswith("60_open:")
    # "no_change" ("Почти нет") is the low/risky answer for day 60 -- must
    # still trigger the admin alert, exactly like the low-rating branches
    # of the other milestones.
    admin_msgs = [t for _, t, _ in app.bot.sent if "Исследование день 60" in t]
    assert admin_msgs and "НИЗКАЯ ОЦЕНКА" in admin_msgs[0], admin_msgs
    print("3. Day 60 always asks the open follow-up, and the risky answer ('no_change') still alerts the admin")

    # A "big_change" (good) answer must ALSO get the open follow-up -- day 60
    # doesn't branch on the rating like day 30/90 do.
    uid1b = 4
    make_user(uid1b, "Оля", "F")
    app1b = FakeApp()
    await bot.send_research_question(app1b, uid1b, 60)
    mid1b = bot._get_notif_msg_id(uid1b, "research")
    ctx1b = FakeCtx(app1b.bot)
    screen1b = FakeMsg(chat_id=uid1b, bot=app1b.bot); screen1b.message_id = mid1b
    upd1b = FakeUpdate(uid1b, data="research_60_big_change", message=screen1b)
    await bot.research_callback(upd1b, ctx1b)
    assert bot.get_user(uid1b).get("research_awaiting", "").startswith("60_open:"), \
        "a GOOD day-60 answer must still get the open follow-up (day 60 always asks, unlike day 30/90)"
    print("4. A good day-60 answer ('big_change') also gets the open follow-up, not a terminal thank-you")

    # ══════════════════════════════════════════════════════════════════════
    # Day 90: terminal milestone -- open follow-up ONLY for the risky answer
    # ("forgot"), otherwise a plain final thank-you (same shape as day 30).
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    make_user(uid2, "Вика", "F")
    app2 = FakeApp()
    await bot.send_research_question(app2, uid2, 90)
    rating_mid2 = bot._get_notif_msg_id(uid2, "research")
    assert rating_mid2 is not None
    print("5. Day 90's rating question is sent")

    ctx2 = FakeCtx(app2.bot)
    rating_screen2 = FakeMsg(chat_id=uid2, bot=app2.bot); rating_screen2.message_id = rating_mid2
    upd2 = FakeUpdate(uid2, data="research_90_habit", message=rating_screen2)
    await bot.research_callback(upd2, ctx2)
    assert (uid2, rating_mid2) in app2.bot.deleted
    assert bot._get_notif_msg_id(uid2, "research") is None
    assert rating_screen2.reply_calls and "Спасибо" in rating_screen2.reply_calls[0][0]
    assert str(bot.get_user(uid2).get("research_awaiting") or "0") == "0", \
        "a terminal day-90 answer must not leave research_awaiting set"
    print("6. Day 90 with a good answer ('habit') is terminal -- deletes the tracked message, plain thank-you, no follow-up")

    uid3 = 3
    make_user(uid3, "Игорь", "M")
    app3 = FakeApp()
    await bot.send_research_question(app3, uid3, 90)
    rating_mid3 = bot._get_notif_msg_id(uid3, "research")
    ctx3 = FakeCtx(app3.bot)
    rating_screen3 = FakeMsg(chat_id=uid3, bot=app3.bot); rating_screen3.message_id = rating_mid3
    upd3 = FakeUpdate(uid3, data="research_90_forgot", message=rating_screen3)
    await bot.research_callback(upd3, ctx3)
    assert not rating_screen3.reply_calls, \
        "the risky day-90 answer must get the open follow-up via send_tracked_notification, not a plain reply"
    assert bot.get_user(uid3).get("research_awaiting", "").startswith("90_open:")
    admin_msgs3 = [t for _, t, _ in app3.bot.sent if "Исследование день 90" in t]
    assert admin_msgs3 and "НИЗКАЯ ОЦЕНКА" in admin_msgs3[0], admin_msgs3
    print("7. Day 90 with the risky answer ('forgot') gets the open follow-up and alerts the admin")

    print("\nALL RESEARCH-DAY60-90 TESTS PASSED")


asyncio.run(main())
