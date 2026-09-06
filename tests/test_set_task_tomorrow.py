import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_set_task_tomorrow.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeMessage:
    def __init__(self, chat_id=1):
        self.chat_id = chat_id
        self.message_id = 900
        self.sent = []

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
        self.effective_chat = FakeChat(uid)
        self.effective_message = None
        self.callback_query = FakeQuery(uid, data, message)
        self.message = None
        self.pre_checkout_query = None


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
    # Real request (IDEAS.md 2026-08-26): "поставь задачу" via free text only
    # worked for TODAY (A/B1-C3 slots) -- the exact same phrasing for
    # TOMORROW ("поставь на завтра задачу — ...") still required the full
    # evening_plan_kb button flow. New handle_set_task_tomorrow_intent
    # mirrors handle_set_task_intent, writing directly into the "evening"
    # diary's e_a/e_b1-e_c3 slots so it reaches tomorrow's morning via the
    # SAME get_latest_evening_plan path the full ritual uses.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    today = bot.evening_day(TBILISI).isoformat()

    # 1. First call fills the first empty slot (e_a) and confirms with its
    #    label.
    msg1 = FakeMessage(uid)
    await bot.handle_set_task_tomorrow_intent(msg1, FakeCtx(), uid, "Созвониться с врачом")
    evening = bot.get_diary(uid, "evening", today)
    assert evening.get("e_a") == "Созвониться с врачом", evening
    assert "задачу A" in msg1.sent[-1][0], msg1.sent[-1][0]
    print("1. First call fills the first empty tomorrow-slot (e_a) and confirms with its label")

    # 2. A second call (no explicit slot) fills the NEXT empty slot (e_b1),
    #    not overwriting e_a.
    msg2 = FakeMessage(uid)
    await bot.handle_set_task_tomorrow_intent(msg2, FakeCtx(), uid, "Купить билеты")
    evening2 = bot.get_diary(uid, "evening", today)
    assert evening2.get("e_a") == "Созвониться с врачом", "e_a must not be overwritten"
    assert evening2.get("e_b1") == "Купить билеты", evening2
    print("2. A second call without an explicit slot fills the next empty slot, without touching the first")

    # 3. An explicit slot overwrites that exact slot, even if already filled.
    msg3 = FakeMessage(uid)
    await bot.handle_set_task_tomorrow_intent(msg3, FakeCtx(), uid, "Другое дело", slot_key="e_a")
    evening3 = bot.get_diary(uid, "evening", today)
    assert evening3.get("e_a") == "Другое дело", evening3
    print("3. An explicit slot overwrites exactly that slot, even if already filled")

    # 4. Once all six slots are full, a friendly message is shown instead of
    #    silently overwriting something.
    for key, text in [("e_b2", "t2"), ("e_c1", "t3"), ("e_c2", "t4"), ("e_c3", "t5")]:
        await bot.handle_set_task_tomorrow_intent(FakeMessage(uid), FakeCtx(), uid, text, slot_key=key)
    msg_full = FakeMessage(uid)
    await bot.handle_set_task_tomorrow_intent(msg_full, FakeCtx(), uid, "Ещё одно дело")
    assert "уже заняты" in msg_full.sent[-1][0], msg_full.sent[-1][0]
    evening_full = bot.get_diary(uid, "evening", today)
    assert evening_full.get("e_a") == "Другое дело", "nothing must have been overwritten when full"
    print("4. Once all six tomorrow-slots are full, a friendly message is shown, nothing is overwritten")

    # 5. The task set for tomorrow actually surfaces via get_latest_evening_plan
    #    -- the same path morning_notification uses -- WITHOUT ever running
    #    the full evening ritual.
    plan = bot.get_latest_evening_plan(uid)
    assert plan.get("e_a") == "Другое дело", plan
    print("5. The task set via free text surfaces through get_latest_evening_plan, same as the full ritual")

    # 6. Isolation: a DIFFERENT user's tomorrow-slots start empty and are
    #    filled independently.
    uid2 = 2
    make_user(uid2, "Вика")
    msg6 = FakeMessage(uid2)
    await bot.handle_set_task_tomorrow_intent(msg6, FakeCtx(), uid2, "Задача Вики")
    evening_u2 = bot.get_diary(uid2, "evening", today)
    assert evening_u2.get("e_a") == "Задача Вики", evening_u2
    evening_u1_untouched = bot.get_diary(uid, "evening", today)
    assert evening_u1_untouched.get("e_a") == "Другое дело", "must not leak between users"
    print("6. Tomorrow-slots are tracked independently per user")

    # 7. evening_start's FRESH (non-resuming) start rehydrates any tomorrow-
    #    plan already set via free text into ctx.user_data -- otherwise
    #    finish_evening/checkpoint_evening_progress (which read ONLY
    #    ctx.user_data) would silently wipe it with an empty string the
    #    moment the user actually runs the evening ritual.
    uid3 = 3
    make_user(uid3, "Игорь")
    await bot.handle_set_task_tomorrow_intent(FakeMessage(uid3), FakeCtx(), uid3, "Заранее поставленная задача")
    orig_evening_day = bot.evening_day
    bot.evening_day = lambda tz: datetime.now(tz).replace(
        year=int(today[:4]), month=int(today[5:7]), day=int(today[8:10])
    ).date()
    try:
        ctx3 = FakeCtx()  # empty user_data -- a genuinely fresh start, not resuming
        upd3 = FakeUpdate(uid3, "go_evening", FakeMessage(uid3))
        await bot.evening_start(upd3, ctx3)
    finally:
        bot.evening_day = orig_evening_day
    assert ctx3.user_data.get("e_a") == "Заранее поставленная задача", \
        f"a fresh evening_start must rehydrate an already-set tomorrow-plan into ctx.user_data, got {ctx3.user_data.get('e_a')!r}"
    print("7. A fresh evening_start rehydrates an already-set tomorrow-plan into ctx.user_data (prevents silent wipe)")

    print("\nALL SET-TASK-TOMORROW TESTS PASSED")


asyncio.run(main())
