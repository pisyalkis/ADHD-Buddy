import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_show_tasks_offers_yesterday_plan.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
        self.edited = []
    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
        return self
    async def reply_text(self, text, **kw):
        return self


class FakeQuery:
    def __init__(self, uid):
        self.from_user = FakeUser(uid); self.message = FakeMsg(uid); self.data = "go_tasks"
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid):
        self.callback_query = FakeQuery(uid)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def has_yesterday_plan_button(reply_markup):
    if reply_markup is None:
        return False
    return any(
        btn.callback_data == "use_yesterday_plan"
        for row in reply_markup.inline_keyboard for btn in row
    )


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Вика', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real report (Виктория): "у меня опять не сохраняются вчерашние
    # задачи". The evening plan ("Планы на завтра") really was saved -- but
    # opening 📋 Задачи directly (Меню -> Задачи, without going through the
    # full morning ritual's warmup step) showed a bare "задачи ещё не
    # заданы" with no way to see or apply yesterday's plan at all. Only the
    # full ritual's warmup screen had the "Взять как задачи на сегодня"
    # button (use_yesterday_plan_callback / callback_data
    # "use_yesterday_plan").
    # ══════════════════════════════════════════════════════════════════════
    tz = bot.get_user_tz(bot.get_user(uid))
    yesterday = (datetime.now(tz).date() - timedelta(days=1)).isoformat()
    bot.save_diary(uid, "evening", {
        "e_ach": "", "e_praise": "", "e_highlights": "",
        "e_a": "Поправить переменные на кампейне",
        "e_b1": "Заполнить таблицу по ретро биржи", "e_b2": "Побегать",
        "e_c1": "Залогировать время", "e_c2": "Пожарить сердечки", "e_c3": "Стирка светлое",
        "e_selfcare": [], "e_energy": 0, "e_tasks_done": [],
    }, for_date=yesterday)

    # Sanity: today's morning is genuinely empty (nothing set yet).
    today = datetime.now(tz).date().isoformat()
    assert not bot.get_diary(uid, "morning", today), "sanity: today's morning must start empty"

    upd = FakeUpdate(uid)
    await bot.show_tasks(upd, FakeCtx())
    text, kb = upd.callback_query.message.edited[-1]
    assert "задачи ещё не заданы" in text, text
    assert has_yesterday_plan_button(kb), \
        f"show_tasks (📋 Задачи opened directly) must offer yesterday's evening plan, got kb={kb}"
    print("1. show_tasks (opened directly, not via full morning ritual) offers yesterday's evening plan")

    # And tapping it must actually work from here -- reuses the existing,
    # already-correct use_yesterday_plan_callback (same callback_data,
    # globally registered, not scoped to any one screen).
    await bot.use_yesterday_plan_callback(upd, FakeCtx())
    morning_now = bot.get_diary(uid, "morning", today)
    assert morning_now.get("focus") == "Поправить переменные на кампейне", morning_now
    assert morning_now.get("b1") == "Заполнить таблицу по ретро биржи", morning_now
    print("2. Tapping it from here fills today's tasks from yesterday's plan, same as from the morning ritual")

    # If there's genuinely no evening plan to offer, the button must not appear.
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Новый', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    upd2 = FakeUpdate(uid2)
    await bot.show_tasks(upd2, FakeCtx())
    text2, kb2 = upd2.callback_query.message.edited[-1]
    assert not has_yesterday_plan_button(kb2), \
        f"show_tasks must NOT offer a nonexistent evening plan, got kb={kb2}"
    print("3. show_tasks does not offer a nonexistent evening plan for a brand-new user")

    print("\nALL SHOW-TASKS-OFFERS-YESTERDAY-PLAN TESTS PASSED")


asyncio.run(main())
