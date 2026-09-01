import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_evening_plan_carryover.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data)
        self.message = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # The original evening-plan-carryover scenario (Artem: "поставил задачи
    # вчера вечером, а сегодня их нет") and its follow-up (Victoria: "у меня
    # опять не сохраняются вчерашние задачи") are now covered end-to-end by
    # test_tasks_auto_apply_yesterday_plan.py (apply_yesterday_plan_if_empty,
    # morning_start, show_tasks, no-clobber, no-plan-graceful). What's left
    # specific to THIS file is an unrelated regression sanity check that has
    # nothing to do with the carry-over feature itself.
    # ══════════════════════════════════════════════════════════════════════
    uid4 = 4
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (4, 'Четвёртый', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid4, timezone="Asia/Tbilisi")
    today4 = bot.datetime.now(bot.get_user_tz(bot.get_user(uid4))).date().isoformat()
    bot.save_diary(uid4, "morning", {k: "" for k in bot.TASK_KEYS}, for_date=today4)
    ctx_mid = FakeCtx()
    upd_mid = FakeUpdate(uid4, data="mid_nostart")
    await bot.midday_callback(upd_mid, ctx_mid)
    mid_text = upd_mid.callback_query.message.last_text
    assert "уже сделаны" not in mid_text, mid_text
    print("1. Sanity: the merged PR #135 fix (midday_callback false completion claim) is still live")

    print("\nALL EVENING-PLAN-CARRYOVER TESTS PASSED")


asyncio.run(main())
