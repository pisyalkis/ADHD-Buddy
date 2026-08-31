import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_evening_checklist_pool_cleanup.db")
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
    async def edit_reply_markup(self, **kw):
        pass


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
        self.bot = FakeBot(1)


class FakeBot:
    def __init__(self, uid):
        self.uid = uid
    async def unpin_chat_message(self, **kw): pass
    async def delete_message(self, **kw): pass
    async def send_message(self, **kw): pass


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    tz = bot.get_user_tz(bot.get_user(uid))
    today = datetime.now(tz).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: "список дел вечером снова показывал те же задачи, хотя
    # они помечены выполненными" -- task_done_callback (📋 Задачи checkbox)
    # already cleans up a matching 📥 Список дел entry when a task is marked
    # done, but the evening ritual's OWN "Что получилось?" checklist
    # (toggle_task_done) never did the same, so a task completed there
    # left its pool entry behind forever, still suggested as a candidate
    # for tomorrow's plan (evening_plan_kb).
    # ══════════════════════════════════════════════════════════════════════
    bot.add_pool_task(uid, "Позвонить маме")
    bot.save_diary(uid, "morning", {"focus": "Позвонить маме"}, for_date=today)

    ctx = FakeCtx()
    ctx.user_data["e_morning_date"] = today
    ctx.user_data["e_tasks_done"] = []

    # Mark "focus" done via the EVENING CHECKLIST (not via 📋 Задачи).
    upd = FakeUpdate(uid, data="td_focus")
    await bot.toggle_task_done(upd, ctx)
    assert ctx.user_data["e_tasks_done"] == ["focus"]

    await bot.finish_evening(FakeMsg(), uid, ctx)

    remaining = [t["text"] for t in bot.get_pool_tasks(uid)]
    assert "Позвонить маме" not in remaining, \
        f"a task completed via the evening checklist must clean up its matching pool entry too, got {remaining}"
    print("1. finish_evening cleans up a pool entry for a task marked done via the evening checklist (text match, no pool link)")

    # Same, but this time the task WAS picked from the pool (has a real
    # _pool_link_ -- must be removed by id, and the link itself cleared
    # from the morning diary row).
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Второй', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    bot.add_pool_task(uid2, "Забрать посылку")
    pool_item = bot.get_pool_tasks(uid2)[0]
    bot.save_diary(uid2, "morning", {"focus": "Забрать посылку", "_pool_link_focus": pool_item["id"]}, for_date=today)

    ctx2 = FakeCtx()
    ctx2.bot = FakeBot(2)
    ctx2.user_data["e_morning_date"] = today
    ctx2.user_data["e_tasks_done"] = []
    upd2 = FakeUpdate(uid2, data="td_focus")
    await bot.toggle_task_done(upd2, ctx2)
    await bot.finish_evening(FakeMsg(), uid2, ctx2)

    remaining2 = [t["text"] for t in bot.get_pool_tasks(uid2)]
    assert "Забрать посылку" not in remaining2, remaining2
    morning2 = bot.get_diary(uid2, "morning", today)
    assert "_pool_link_focus" not in morning2, \
        "the stale _pool_link_ marker must be cleared from the morning diary row too"
    print("2. finish_evening also cleans up a pool-linked task (by id) and clears the stale _pool_link_ marker")

    # Sanity: a task NOT marked done keeps its pool entry (still an open
    # candidate for tomorrow's plan) -- must not over-clean.
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Третий', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone="Asia/Tbilisi")
    bot.add_pool_task(uid3, "Другое дело")
    bot.save_diary(uid3, "morning", {"focus": "Другое дело"}, for_date=today)
    ctx3 = FakeCtx()
    ctx3.bot = FakeBot(3)
    ctx3.user_data["e_morning_date"] = today
    ctx3.user_data["e_tasks_done"] = []
    await bot.finish_evening(FakeMsg(), uid3, ctx3)
    remaining3 = [t["text"] for t in bot.get_pool_tasks(uid3)]
    assert "Другое дело" in remaining3, \
        f"a task NOT marked done must keep its pool entry, got {remaining3}"
    print("3. A task left undone keeps its pool entry (no over-cleaning)")

    print("\nALL EVENING-CHECKLIST-POOL-CLEANUP TESTS PASSED")


asyncio.run(main())
