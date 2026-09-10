import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_walk_tasks_start_carries_yesterday_plan.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [97000]

    def __init__(self, chat_id=1, message_id=None):
        self.chat_id = chat_id
        self.message_id = message_id if message_id is not None else FakeMsg._next_id[0]
        if message_id is None:
            FakeMsg._next_id[0] += 1
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return FakeMsg(self.chat_id)

    async def edit_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message

    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data, message):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message)
        self.message = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real live bug report (regression from #310 "Да, поставить" ведёт сразу
    # в Задачу A): morning_task_offer_yes now delegates straight into
    # walk_tasks_start, which read today's (empty) morning diary directly --
    # WITHOUT calling apply_yesterday_plan_if_empty first. Yesterday's
    # evening plan ("Планы на завтра") was silently never carried over, and
    # the walk started asking for Task A from scratch even though the user
    # had already planned it the night before.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    today = datetime.now(TBILISI).date().isoformat()
    yesterday = (datetime.now(TBILISI).date() - timedelta(days=1)).isoformat()

    # Yesterday evening: planned A and B1 for today ("Планы на завтра").
    bot.save_diary(uid, "evening", {
        "e_a": "Сделать отчёт", "e_b1": "Позвонить маме", "e_energy": 3,
    }, for_date=yesterday)

    # 1. walk_tasks_start (the function morning_task_offer_yes now delegates
    #    to) must carry yesterday's plan over BEFORE picking the first empty
    #    slot -- it should jump straight to B2 (first still-empty), not A.
    ctx = FakeCtx()
    upd = FakeUpdate(uid, "walk_tasks", FakeMsg(uid))
    await bot.walk_tasks_start(upd, ctx)
    morning_after = bot.get_diary(uid, "morning", today)
    assert morning_after.get("focus") == "Сделать отчёт", \
        f"yesterday's evening plan for Task A must be carried over: {morning_after}"
    assert morning_after.get("b1") == "Позвонить маме", \
        f"yesterday's evening plan for B1 must be carried over: {morning_after}"
    sent_text = upd.callback_query.message.sent[-1][0]
    assert "B2" in sent_text, \
        f"the walk must jump to B2 (first empty AFTER the carried-over plan), not restart at A: {sent_text}"
    print("1. walk_tasks_start carries yesterday's evening plan over before starting the walk (bug fix)")

    # 2. End-to-end through the actual regressed entry point:
    #    morning_task_offer_yes ("Да, поставить" after the morning ritual)
    #    must also carry the plan over, not just direct calls to
    #    walk_tasks_start.
    uid2 = 2
    make_user(uid2, "Вика")
    bot.save_diary(uid2, "evening", {
        "e_a": "Подготовить презентацию", "e_energy": 3,
    }, for_date=yesterday)
    ctx2 = FakeCtx()
    upd2 = FakeUpdate(uid2, "morning_tasks_yes", FakeMsg(uid2))
    await bot.morning_task_offer_yes(upd2, ctx2)
    morning2 = bot.get_diary(uid2, "morning", today)
    assert morning2.get("focus") == "Подготовить презентацию", \
        f"morning_task_offer_yes must carry yesterday's plan over via walk_tasks_start: {morning2}"
    sent_text2 = upd2.callback_query.message.sent[-1][0]
    assert "B1" in sent_text2, \
        f"must jump to B1 (A already carried over from yesterday), not ask for A again: {sent_text2}"
    print("2. morning_task_offer_yes ('Да, поставить') also carries the plan over end-to-end (the live bug)")

    # 3. Regression: with NO yesterday plan at all, the walk still correctly
    #    starts at A, exactly as before.
    uid3 = 3
    make_user(uid3, "Игорь")
    ctx3 = FakeCtx()
    upd3 = FakeUpdate(uid3, "morning_tasks_yes", FakeMsg(uid3))
    await bot.morning_task_offer_yes(upd3, ctx3)
    morning3 = bot.get_diary(uid3, "morning", today)
    assert not morning3.get("focus"), morning3
    sent_text3 = upd3.callback_query.message.sent[-1][0]
    assert "A" in sent_text3, f"with no evening plan, must still start at Task A: {sent_text3}"
    print("3. With no yesterday plan, the walk still starts at Task A as before (no regression)")

    print("\nALL WALK-TASKS-START-CARRIES-YESTERDAY-PLAN TESTS PASSED")


asyncio.run(main())
