import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_evening_c_tasks_and_carryover.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
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


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = None


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQueryMsg:
    async def reply_text(self, text, **kw):
        return self


class FakeQuery:
    def __init__(self, uid):
        self.from_user = FakeUser(uid)
        self.message = FakeQueryMsg()
    async def answer(self, *a, **kw): pass


class FakeUpdate:
    def __init__(self, uid):
        self.callback_query = FakeQuery(uid)
        self.effective_user = FakeUser(uid)


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")
    tz = bot.get_user_tz(bot.get_user(uid))
    today_iso = datetime.now(tz).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Bug (Artem, screenshot): "День закрыт!" summary's "Планы на завтра"
    # dropped e_c2/e_c3 entirely -- only e_c1 ever showed, even though
    # build_day_card_text (a separate, later-written code path) already
    # correctly includes all 6 fields. Classic drift-between-duplicates bug.
    # ══════════════════════════════════════════════════════════════════════
    bot.save_diary(uid, "morning", {"focus": "Запостить статью"}, for_date=today_iso)
    ctx = FakeCtx()
    ctx.user_data.update({
        # Фиксируем дату утра явно -- иначе finish_evening резолвит её
        # через evening_day(tz), которая до 4 утра расходится с обычной
        # календарной датой (под которой мы тут сохраняем морнинг), и тест
        # стал бы зависеть от того, в какой момент суток он реально запущен.
        "e_morning_date": today_iso,
        "e_ach": "", "e_praise": "", "e_highlights": "",
        "e_selfcare": [], "e_energy": 3,
        "e_a": "Запостить первую статью на канал",
        "e_b1": "Структура канала", "e_b2": "Как привлекать аудиторию",
        "e_c1": "Разобраться со списком дел", "e_c2": "Второе дело C", "e_c3": "Третье дело C",
        "e_tasks_done": [],
    })
    msg = FakeMsg()
    await bot.finish_evening(msg, uid, ctx)
    summary = msg.last_text
    assert "Второе дело C" in summary, summary
    assert "Третье дело C" in summary, summary
    print("1. finish_evening's 'Планы на завтра' now includes e_c2 and e_c3, not just e_c1")

    # ══════════════════════════════════════════════════════════════════════
    # New feature (Artem's request): tasks from today that were NOT marked
    # done must land in 📥 Список дел, so they aren't lost. Carried over by
    # tasks_done_finish now -- as soon as "Что получилось?" is confirmed,
    # not at the very end of the ritual (finish_evening) -- so it survives
    # even if the rest of the evening ritual is abandoned.
    # ══════════════════════════════════════════════════════════════════════
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Аня', 'F')")
    conn.commit(); conn.close()
    uid2 = 2
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    bot.save_diary(uid2, "morning", {
        "focus": "Сделать отчёт",       # done
        "b1": "Убраться дома",           # NOT done -- must be carried over
        "b2": "Позвонить маме",          # NOT done -- must be carried over
        "c1": "",                        # empty -- nothing to carry
    }, for_date=today_iso)
    ctx2 = FakeCtx()
    ctx2.user_data.update({
        "e_morning_date": today_iso,
        "e_tasks_done": ["focus"],  # only focus marked done
    })
    await bot.tasks_done_finish(FakeUpdate(uid2), ctx2)
    pool = [t["text"] for t in bot.get_pool_tasks(uid2)]
    assert "Убраться дома" in pool, pool
    assert "Позвонить маме" in pool, pool
    assert "Сделать отчёт" not in pool, \
        "the DONE task must not be carried over into the pool"
    print("2. Unfinished tasks (not marked done) land in 📥 Список дел as soon as tasks_done_finish runs; done tasks don't")

    # The rest of the evening ritual (finish_evening) must NOT carry them
    # over AGAIN -- that would duplicate what tasks_done_finish already did.
    await bot.finish_evening(FakeMsg(), uid2, ctx2)
    pool_after = [t["text"] for t in bot.get_pool_tasks(uid2)]
    assert pool_after.count("Убраться дома") == 1 and pool_after.count("Позвонить маме") == 1, \
        f"finish_evening must not carry the same tasks over a second time, got {pool_after}"
    print("2b. finish_evening (the rest of the ritual) does not duplicate what tasks_done_finish already carried over")

    # ══════════════════════════════════════════════════════════════════════
    # A task that was originally PICKED from the pool but still carries a
    # LEGACY _pool_link_key (saved before pool selection started deleting
    # the item immediately) must NOT be duplicated -- it's still sitting
    # there untouched, adding it again would double it.
    # ══════════════════════════════════════════════════════════════════════
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Витя', 'M')")
    conn.commit(); conn.close()
    uid3 = 3
    bot.update_user(uid3, timezone="Asia/Tbilisi")
    bot.add_pool_task(uid3, "Купить лампочки")
    pool_item = bot.get_pool_tasks(uid3)[0]
    bot.save_diary(uid3, "morning", {
        "focus": "Купить лампочки",
        f"_pool_link_focus": pool_item["id"],
    }, for_date=today_iso)
    ctx3 = FakeCtx()
    ctx3.user_data.update({
        "e_morning_date": today_iso,
        "e_tasks_done": [],  # not done
    })
    await bot.tasks_done_finish(FakeUpdate(uid3), ctx3)
    pool3 = [t["text"] for t in bot.get_pool_tasks(uid3)]
    assert pool3.count("Купить лампочки") == 1, \
        f"a task with a legacy pool link must not be duplicated, got {pool3}"
    print("3. A task with a legacy _pool_link_ is not duplicated on carryover")

    print("\nALL EVENING-C-TASKS-AND-CARRYOVER TESTS PASSED")


asyncio.run(main())
