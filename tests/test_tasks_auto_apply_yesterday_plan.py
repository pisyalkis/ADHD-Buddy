import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_tasks_auto_apply_yesterday_plan.db")
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
        self.sent = []
    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
        return self
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
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
        self.message = FakeMsg(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def seed_evening_plan(uid, for_date):
    bot.save_diary(uid, "evening", {
        "e_ach": "", "e_praise": "", "e_highlights": "",
        "e_a": "Поправить переменные на кампейне",
        "e_b1": "Заполнить таблицу по ретро биржи", "e_b2": "Побегать",
        "e_c1": "Залогировать время", "e_c2": "Пожарить сердечки", "e_c3": "Стирка светлое",
        "e_selfcare": [], "e_energy": 0, "e_tasks_done": [],
    }, for_date=for_date)


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real report (Виктория): "у меня опять не сохраняются вчерашние
    # задачи" -- follow-up: even WITH a "take yesterday's plan" button
    # (previous fix), seeing "задачи ещё не заданы" under your own plan is
    # still frustrating -- it was a conscious decision made the night
    # before, not a blank slate. By explicit request, this is now fully
    # automatic and silent: opening any of the quick task screens with an
    # empty day just materializes yesterday's plan, no tap required.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Вика', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    tz = bot.get_user_tz(bot.get_user(uid))
    today = datetime.now(tz).date().isoformat()
    yesterday = (datetime.now(tz).date() - timedelta(days=1)).isoformat()

    # ── 1. apply_yesterday_plan_if_empty itself ─────────────────────────────
    seed_evening_plan(uid, yesterday)
    assert not bot.get_diary(uid, "morning", today), "sanity: today's morning starts empty"
    morning = bot.apply_yesterday_plan_if_empty(uid, today, bot.get_diary(uid, "morning", today))
    assert morning.get("focus") == "Поправить переменные на кампейне", morning
    assert morning.get("b1") == "Заполнить таблицу по ретро биржи", morning
    assert morning.get("c3") == "Стирка светлое", morning
    persisted = bot.get_diary(uid, "morning", today)
    assert persisted.get("focus") == "Поправить переменные на кампейне", \
        "must be persisted to the DB, not just returned in memory"
    print("1. apply_yesterday_plan_if_empty fills and persists an empty day from yesterday's evening plan")

    # ── 2. Doesn't touch a day that already has real tasks ─────────────────
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Настя', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    seed_evening_plan(uid2, yesterday)
    bot.save_diary(uid2, "morning", {"focus": "Своя задача, введена вручную"}, for_date=today)
    morning2 = bot.apply_yesterday_plan_if_empty(uid2, today, bot.get_diary(uid2, "morning", today))
    assert morning2.get("focus") == "Своя задача, введена вручную", \
        "must NOT overwrite a day where at least one real task already exists"
    assert not morning2.get("b1"), \
        "must not fill OTHER slots either once the day is no longer considered empty"
    print("2. apply_yesterday_plan_if_empty leaves an already-started day untouched")

    # ── 3. Nothing to apply when there's no usable evening plan ────────────
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Новый', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone="Asia/Tbilisi")
    morning3 = bot.apply_yesterday_plan_if_empty(uid3, today, bot.get_diary(uid3, "morning", today))
    assert not any(morning3.get(k) for k, _ in bot.TASK_FIELDS), morning3
    assert not bot.get_diary(uid3, "morning", today), "must not write an empty row for nothing"
    print("3. apply_yesterday_plan_if_empty is a no-op for a brand-new user with no evening plan")

    # ── 4. show_tasks (📋 Задачи opened directly) auto-applies silently ────
    uid4 = 4
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (4, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid4, timezone="Asia/Tbilisi")
    seed_evening_plan(uid4, yesterday)
    upd4 = FakeUpdate(uid4)
    await bot.show_tasks(upd4, FakeCtx())
    text4, kb4 = upd4.callback_query.message.edited[-1]
    assert "задачи ещё не заданы" not in text4, \
        f"the empty-state message must NOT appear once yesterday's plan was silently applied: {text4}"
    assert "Поправить переменные на кампейне" in text4, text4
    print("4. show_tasks opened directly no longer shows 'задачи ещё не заданы' when a plan exists")

    # ── 5. show_tasks with genuinely nothing still shows the honest empty state ─
    uid5 = 5
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (5, 'Пустой', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid5, timezone="Asia/Tbilisi")
    upd5 = FakeUpdate(uid5)
    await bot.show_tasks(upd5, FakeCtx())
    text5, kb5 = upd5.callback_query.message.edited[-1]
    assert "задачи ещё не заданы" in text5, text5
    print("5. show_tasks still honestly says 'задачи ещё не заданы' when there's really nothing to apply")

    # ── 6. По просьбе: разминка (☀️ Утро / morning_start) тоже применяет
    # план автоматически, без отдельной кнопки -- та же логика, что и на
    # быстрых экранах. Кнопка "Взять как задачи на сегодня" убрана
    # (use_yesterday_plan_callback удалён как недостижимый мёртвый код).
    uid6 = 6
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (6, 'Ритуал', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid6, timezone="Asia/Tbilisi")
    seed_evening_plan(uid6, yesterday)
    upd6 = FakeUpdate(uid6)
    await bot.morning_start(upd6, FakeCtx())
    morning6 = bot.get_diary(uid6, "morning", today)
    assert morning6.get("focus") == "Поправить переменные на кампейне", morning6
    assert morning6.get("c3") == "Стирка светлое", morning6
    rendered = upd6.callback_query.message.edited + upd6.callback_query.message.sent
    for text, kb in rendered:
        if kb is None:
            continue
        flat = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "use_yesterday_plan" not in flat, \
            f"the removed 'Взять как задачи на сегодня' button must not appear anywhere: {flat}"
    print("6. morning_start (☀️ Утро greeting) also auto-applies yesterday's plan, no button needed")

    # ── 7. morning_start leaves an already-started day untouched, same as
    # the quick screens (sanity -- shares the same helper).
    uid7 = 7
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (7, 'Свой план', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid7, timezone="Asia/Tbilisi")
    seed_evening_plan(uid7, yesterday)
    bot.save_diary(uid7, "morning", {"focus": "Уже сама решила"}, for_date=today)
    upd7 = FakeUpdate(uid7)
    await bot.morning_start(upd7, FakeCtx())
    morning7 = bot.get_diary(uid7, "morning", today)
    assert morning7.get("focus") == "Уже сама решила", morning7
    assert not morning7.get("b1"), morning7
    print("7. morning_start does not overwrite a day that already has a real task set")

    print("\nALL TASKS-AUTO-APPLY-YESTERDAY-PLAN TESTS PASSED")


asyncio.run(main())
