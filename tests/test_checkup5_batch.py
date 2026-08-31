import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup5_batch.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
import bot
bot.init_db()


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})
        self.callback_query = FakeQuery(uid, data) if data is not None else None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


class FakeBot:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail
    async def send_message(self, chat_id, text, **kw):
        if self.fail:
            raise RuntimeError("simulated Telegram failure")
        self.sent.append((chat_id, text, kw.get("reply_markup")))


class FakeApp:
    def __init__(self, fail=False):
        self.bot = FakeBot(fail=fail)


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")
    tz = bot.get_user_tz(bot.get_user(uid))
    today = datetime.now(tz).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Bug: walk_finish_callback / task_done_callback / reminder_cancel_item /
    # show_task_pool_delete / pool_delete_item didn't clear stale awaiting_*
    # flags -- a leftover flag from an unrelated flow could hijack the next
    # ordinary message.
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    ctx.user_data["awaiting_task_edit"] = "b1"
    upd = FakeUpdate(uid, data="walk_finish")
    await bot.walk_finish_callback(upd, ctx)
    assert "awaiting_task_edit" not in ctx.user_data, ctx.user_data
    print("1. walk_finish_callback clears a stale awaiting_task_edit")

    bot.save_diary(uid, "morning", {"focus": "Задача A"}, for_date=today)
    ctx2 = FakeCtx()
    ctx2.user_data["awaiting_name"] = True
    upd2 = FakeUpdate(uid, data="task_done_focus")
    await bot.task_done_callback(upd2, ctx2)
    assert ctx2.user_data.get("awaiting_name") is False, ctx2.user_data
    print("2. task_done_callback clears a stale awaiting_name")

    when = (datetime.now(tz)).isoformat()
    bot.add_reminder(uid, "Позвонить", when)
    rem_id = bot.get_reminders(uid)[0]["id"]
    ctx3 = FakeCtx()
    ctx3.user_data["awaiting_city"] = True
    upd3 = FakeUpdate(uid, data=f"remdel_{rem_id}")
    await bot.reminder_cancel_item(upd3, ctx3)
    assert ctx3.user_data.get("awaiting_city") is False, ctx3.user_data
    print("3. reminder_cancel_item clears a stale awaiting_city")

    bot.add_pool_task(uid, "Купить хлеб")
    ctx4 = FakeCtx()
    ctx4.user_data["awaiting_pool_add"] = True
    upd4 = FakeUpdate(uid, data="pool_del_menu")
    await bot.show_task_pool_delete(upd4, ctx4)
    assert ctx4.user_data.get("awaiting_pool_add") is False, ctx4.user_data
    print("4a. show_task_pool_delete clears a stale awaiting_pool_add")

    pool_item = bot.get_pool_tasks(uid)[0]
    ctx5 = FakeCtx()
    ctx5.user_data["awaiting_reminder_add"] = True
    upd5 = FakeUpdate(uid, data=f"pooldel_{pool_item['id']}")
    await bot.pool_delete_item(upd5, ctx5)
    assert ctx5.user_data.get("awaiting_reminder_add") is False, ctx5.user_data
    print("4b. pool_delete_item clears a stale awaiting_reminder_add")

    # ══════════════════════════════════════════════════════════════════════
    # Bug: send_research_question marked research_done BEFORE attempting the
    # send -- a failed send permanently lost that milestone.
    # ══════════════════════════════════════════════════════════════════════
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Тест', 'F')")
    conn.commit(); conn.close()
    uid2 = 2
    bot.update_user(uid2, timezone="Asia/Tbilisi")

    failing_app = FakeApp(fail=True)
    try:
        await bot.send_research_question(failing_app, uid2, 3)
    except Exception:
        pass
    assert "3" not in (bot.get_user(uid2).get("research_done") or "").split(","), \
        "a failed send must NOT mark the research milestone as done"
    print("5a. A failed research-question send does not mark the milestone done (can retry)")

    ok_app = FakeApp(fail=False)
    await bot.send_research_question(ok_app, uid2, 3)
    assert "3" in bot.get_user(uid2)["research_done"].split(",")
    assert len(ok_app.bot.sent) == 1
    print("5b. A successful research-question send correctly marks the milestone done")

    # ══════════════════════════════════════════════════════════════════════
    # Bug: build_day_card_text read done-marks from evening["e_tasks_done"]
    # (only populated after the evening ritual runs) instead of the live
    # "tasks_done" diary block that 📋 Задачи actually uses all day.
    # ══════════════════════════════════════════════════════════════════════
    bot.save_diary(uid, "morning", {"focus": "Сходить к врачу", "b1": "Купить хлеб"}, for_date=today)
    bot.mark_tasks_done(uid, ["focus"], for_date=today)
    card_text = bot.build_day_card_text(uid, today)
    focus_line = next(l for l in card_text.split("\n") if "Сходить к врачу" in l)
    b1_line = next(l for l in card_text.split("\n") if "Купить хлеб" in l)
    assert focus_line.startswith("✅"), \
        f"a task marked done via 📋 Задачи (not the evening ritual) must show as done on the day card, got: {focus_line!r}"
    assert not b1_line.startswith("✅"), b1_line
    print("6. Day card shows tasks marked done via 📋 Задачи, not just via the evening ritual")

    print("\nALL CHECKUP-5 BATCH TESTS PASSED")


asyncio.run(main())
