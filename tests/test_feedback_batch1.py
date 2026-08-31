import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_feedback_batch1.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real feedback #2: "закрыла день раньше 9 вечера (бот предложил) --
    # но в 9 снова пришло предложение закрыть день". evening_sent_date only
    # guards against re-sending the same scheduled notification twice; it
    # never checked whether the evening was already genuinely closed.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    tz = bot.get_user_tz(bot.get_user(uid))
    today = bot.evening_day(tz).isoformat()
    bot.save_diary(uid, "evening", {"e_energy": 3, "e_ach": "Дописал(а) отчёт"}, for_date=today)

    app = FakeApp()
    result = await bot.evening_notification(app, uid)
    assert result is True, "must report handled=True so the scheduler marks evening_sent_date and stops retrying"
    assert app.bot.sent == [], f"must not re-send the closing prompt once the evening is already closed, got {app.bot.sent}"
    print("1. evening_notification skips sending when the evening is already closed today")

    # Sanity: a user who has NOT closed the evening yet still gets the prompt.
    uid1b = 10
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (10, 'Не закрыл', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid1b, timezone="Asia/Tbilisi")
    app1b = FakeApp()
    result1b = await bot.evening_notification(app1b, uid1b)
    assert result1b is True
    assert len(app1b.bot.sent) == 1, app1b.bot.sent
    print("2. evening_notification still sends normally when the evening has not been closed yet")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback #4a: "выполнила все дела из списка задач ещё до обеда...
    # бот продолжал спрашивать о нём оставшийся день". Tasks stay in
    # `morning` even once marked done -- the beacon must stop nagging once
    # nothing is left undone.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Второй', 'M')")
    conn.commit(); conn.close()
    bot.update_user(
        uid2, timezone="Asia/Tbilisi",
        beacon_enabled=1, beacon_interval=2, beacon_start="00:00", beacon_end="23:59",
        beacon_last_sent="", morning_filled_at="", midday_sent_date="",
    )
    today2 = datetime.now(bot.get_user_tz(bot.get_user(uid2))).date().isoformat()
    bot.save_diary(uid2, "morning", {"focus": "Написать отчёт"}, for_date=today2)
    bot.save_diary(uid2, "tasks_done", {"done": ["focus"]}, for_date=today2)

    app2 = FakeApp()
    await bot.send_task_beacon(app2, bot.get_user(uid2))
    assert app2.bot.sent == [], \
        f"beacon must not fire once every set task is already marked done, got {app2.bot.sent}"
    print("3. send_task_beacon stays silent once all set tasks are already done")

    # Sanity: one task still undone -> beacon still fires as before.
    uid2b = 20
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (20, 'НеВсё', 'M')")
    conn.commit(); conn.close()
    bot.update_user(
        uid2b, timezone="Asia/Tbilisi",
        beacon_enabled=1, beacon_interval=2, beacon_start="00:00", beacon_end="23:59",
        beacon_last_sent="", morning_filled_at="", midday_sent_date="",
    )
    bot.save_diary(uid2b, "morning", {"focus": "Написать отчёт", "b1": "Позвонить"}, for_date=today2)
    bot.save_diary(uid2b, "tasks_done", {"done": ["focus"]}, for_date=today2)
    app2b = FakeApp()
    await bot.send_task_beacon(app2b, bot.get_user(uid2b))
    assert len(app2b.bot.sent) == 1, "beacon must still fire while a task remains undone"
    print("4. send_task_beacon still fires normally while at least one task remains undone")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback #4b: "не смогла новый [список] составить" once all six
    # slots were occupied -- the "all full" message now surfaces the
    # existing named-slot overwrite trick instead of just pointing at 📋 Задачи.
    # ══════════════════════════════════════════════════════════════════════
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Третий', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone="Asia/Tbilisi")
    today3 = datetime.now(bot.get_user_tz(bot.get_user(uid3))).date().isoformat()
    bot.save_diary(uid3, "morning", {k: f"Дело {k}" for k, _ in bot.TASK_FIELDS}, for_date=today3)
    msg3 = FakeMsg()
    await bot.handle_set_task_intent(msg3, FakeCtx(), uid3, "Новое дело")
    full_text = msg3.sent[0][0]
    assert "назови слот" in full_text.lower() or "поставь как задачу" in full_text.lower(), full_text
    print("5. The 'all six slots full' message now points at the named-slot overwrite trick")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback #3: comma-separated pool entries got merged into one
    # garbled item until she discovered one-per-line -- the add-prompt now
    # says so upfront.
    # ══════════════════════════════════════════════════════════════════════
    upd4 = FakeUpdate(4, data="go_task_pool_add")
    await bot.pool_add_start(upd4, FakeCtx())
    prompt_text = upd4.callback_query.message.sent[0][0]
    assert "с новой строки" in prompt_text, prompt_text
    print("6. pool_add_start's prompt now mentions one item per line upfront")

    print("\nALL FEEDBACK-BATCH-1 TESTS PASSED")


asyncio.run(main())
