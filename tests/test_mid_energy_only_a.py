import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_mid_energy_only_a.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeMsg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self

    async def edit_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


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
        self.callback_query = FakeQuery(uid, data)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def kb_callbacks(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-09-04): the "🔋 Мало энергии" branch of the
    # midday check-in only gave advice text -- no actual action to reduce
    # today's load. Add "🎯 Оставить только А на сегодня": clears B1-C3
    # (moving unfinished ones to 📥 Список дел, dropping already-done ones),
    # only offered when there's something real to trim.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    today = datetime.now(TBILISI).date().isoformat()
    bot.save_diary(uid, "morning", {
        "focus": "Сделать план", "b1": "Купить хлеб", "b2": "Постирать", "c1": "Позвонить маме",
    }, for_date=today)

    # 1. mid_energy shows the "Оставить только А" button when A is set,
    #    not yet done, and there's at least one B/C task to trim.
    upd1 = FakeUpdate(uid, "mid_energy")
    await bot.midday_callback(upd1, FakeCtx())
    _, kb1 = upd1.callback_query.message.sent[-1]
    assert "mid_energy_only_a" in kb_callbacks(kb1), kb_callbacks(kb1)
    print("1. mid_energy offers 'Оставить только А' when there's something real to trim")

    # 2. Tapping it moves the unfinished B/C tasks to the pool and clears
    #    them from today, keeping only A.
    await bot.midday_callback(FakeUpdate(uid, "mid_energy_only_a"), FakeCtx())
    morning_after = bot.get_diary(uid, "morning", today)
    assert morning_after.get("focus") == "Сделать план", morning_after
    assert not morning_after.get("b1") and not morning_after.get("b2") and not morning_after.get("c1"), morning_after
    pool_texts = {t["text"] for t in bot.get_pool_tasks(uid)}
    assert {"Купить хлеб", "Постирать", "Позвонить маме"} <= pool_texts, pool_texts
    print("2. mid_energy_only_a clears B1-C3 from today and carries the unfinished ones into the pool")

    # 3. An ALREADY-DONE B/C task is simply dropped from today, not
    #    duplicated into the pool (it's already accomplished).
    uid2 = 2
    make_user(uid2, "Вика")
    bot.save_diary(uid2, "morning", {"focus": "Главное", "b1": "Уже сделано", "b2": "Ещё не сделано"}, for_date=today)
    bot.save_diary(uid2, "tasks_done", {"done": ["b1"]}, for_date=today)
    await bot.midday_callback(FakeUpdate(uid2, "mid_energy_only_a"), FakeCtx())
    morning2 = bot.get_diary(uid2, "morning", today)
    assert not morning2.get("b1") and not morning2.get("b2"), morning2
    pool_texts2 = {t["text"] for t in bot.get_pool_tasks(uid2)}
    assert "Ещё не сделано" in pool_texts2
    assert "Уже сделано" not in pool_texts2, "an already-done task must not be re-added to the pool"
    print("3. An already-done B/C task is dropped, not duplicated into the pool")

    # 4. No button when A is already done (nothing left to "simplify to").
    uid3 = 3
    make_user(uid3, "Игорь")
    bot.save_diary(uid3, "morning", {"focus": "Готово", "b1": "Ещё есть"}, for_date=today)
    bot.save_diary(uid3, "tasks_done", {"done": ["focus"]}, for_date=today)
    upd3 = FakeUpdate(uid3, "mid_energy")
    await bot.midday_callback(upd3, FakeCtx())
    _, kb3 = upd3.callback_query.message.sent[-1]
    assert "mid_energy_only_a" not in kb_callbacks(kb3), kb_callbacks(kb3)
    print("4. No 'Оставить только А' button once A is already done")

    # 5. No button when there's nothing beyond A to trim.
    uid4 = 4
    make_user(uid4, "Соня")
    bot.save_diary(uid4, "morning", {"focus": "Только одна задача"}, for_date=today)
    upd4 = FakeUpdate(uid4, "mid_energy")
    await bot.midday_callback(upd4, FakeCtx())
    _, kb4 = upd4.callback_query.message.sent[-1]
    assert "mid_energy_only_a" not in kb_callbacks(kb4), kb_callbacks(kb4)
    print("5. No 'Оставить только А' button when there's nothing beyond A to trim")

    print("\nALL MID-ENERGY-ONLY-A TESTS PASSED")


asyncio.run(main())
