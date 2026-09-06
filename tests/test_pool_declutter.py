import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_pool_declutter.db")
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
        self.message_id = 100
        self.edited = []

    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
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


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def add_task_with_age(uid, text, days_ago):
    conn = sqlite3.connect(bot.DB_PATH)
    created = (datetime.now() - timedelta(days=days_ago)).isoformat()
    conn.execute("INSERT INTO tasks(user_id, text, created) VALUES (?, ?, ?)", (uid, text, created))
    conn.commit(); conn.close()


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-28): the task pool is a flat list with
    # no add-date, sorting, or archiving -- it stably grows into an
    # unreadable "graveyard". Minimal declutter: surface each item's age so
    # old items are visually distinguishable, plus a bulk "clear all" with a
    # confirm step (destructive actions get a confirm screen in this file).
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    add_task_with_age(uid, "Свежее дело", 1)
    add_task_with_age(uid, "Старое дело", 30)

    pool = bot.get_pool_tasks(uid)
    text = bot.task_pool_text(pool)
    assert "Свежее дело" in text and "Старое дело" in text
    fresh_line = next(l for l in text.split("\n") if "Свежее дело" in l)
    old_line = next(l for l in text.split("\n") if "Старое дело" in l)
    assert "дн." not in fresh_line, f"a 1-day-old item must not show an age hint, got: {fresh_line}"
    assert "30 дн." in old_line, f"a 30-day-old item must show its age, got: {old_line}"
    print("1. task_pool_text shows an age hint only for items older than POOL_STALE_DAYS")

    # 2. task_pool_kb offers a bulk clear-all button when the pool is non-empty.
    kb = bot.task_pool_kb(pool)
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "pool_clear_menu" in callbacks
    print("2. task_pool_kb offers a '🧹 Очистить весь список' button when the pool isn't empty")

    # 3. pool_clear_menu shows a confirm screen -- does NOT delete anything yet.
    ctx = FakeCtx()
    msg = FakeMsg(uid)
    upd = FakeUpdate(uid, "pool_clear_menu", msg)
    await bot.pool_clear_menu(upd, ctx)
    assert len(bot.get_pool_tasks(uid)) == 2, "pool_clear_menu must only show a confirmation, not delete anything"
    confirm_text, confirm_kb = msg.edited[-1]
    confirm_callbacks = [b.callback_data for row in confirm_kb.inline_keyboard for b in row]
    assert "pool_clear_confirm" in confirm_callbacks
    print("3. pool_clear_menu shows a confirmation screen without deleting anything yet")

    # 4. pool_clear_confirm actually clears the whole pool for that user.
    upd2 = FakeUpdate(uid, "pool_clear_confirm", msg)
    await bot.pool_clear_confirm(upd2, ctx)
    assert bot.get_pool_tasks(uid) == [], "pool_clear_confirm must delete every item in the pool"
    print("4. pool_clear_confirm deletes the entire pool")

    # 5. clear_pool_tasks only touches the calling user's own items, not
    #    another user's pool (sanity -- scoped by user_id).
    uid2 = 2
    make_user(uid2, "Вика")
    add_task_with_age(uid2, "Чужое дело", 1)
    bot.clear_pool_tasks(uid)  # uid's pool is already empty; must not touch uid2
    assert len(bot.get_pool_tasks(uid2)) == 1, "clear_pool_tasks must not touch another user's pool"
    print("5. clear_pool_tasks is scoped to a single user, not global")

    print("\nALL POOL-DECLUTTER TESTS PASSED")


asyncio.run(main())
