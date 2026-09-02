import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_task_pool_integrity.db")
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
        self.from_user = FakeUser(uid); self.message = FakeMsg(uid)
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid):
        self.callback_query = FakeQuery(uid)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug 1: apply_task_edit cleared a task's "done" mark on ANY resave,
    # even resaving the exact same text (e.g. "✏️ Поменять" with no real
    # edit) -- was_filled only checked non-emptiness, not a text change.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()

    ctx = FakeCtx()
    msg = FakeMsg(uid)
    await bot.apply_task_edit(msg, ctx, uid, "focus", "Позвонить врачу")
    bot.save_diary(uid, "tasks_done", {"done": ["focus"]}, for_date=today)
    assert "focus" in bot.get_diary(uid, "tasks_done", today).get("done", [])

    # Resave the SAME text -- done mark must survive.
    ctx2 = FakeCtx()
    msg2 = FakeMsg(uid)
    await bot.apply_task_edit(msg2, ctx2, uid, "focus", "Позвонить врачу")
    done_after_same = bot.get_diary(uid, "tasks_done", today).get("done", [])
    assert "focus" in done_after_same, \
        f"resaving the IDENTICAL text must NOT clear the done mark, got done={done_after_same}"
    print("1. apply_task_edit keeps the done mark when the resaved text is unchanged")

    # Resave with DIFFERENT text -- done mark must be cleared (existing behavior).
    ctx3 = FakeCtx()
    msg3 = FakeMsg(uid)
    await bot.apply_task_edit(msg3, ctx3, uid, "focus", "Написать отчёт")
    done_after_diff = bot.get_diary(uid, "tasks_done", today).get("done", [])
    assert "focus" not in done_after_diff, \
        f"resaving with DIFFERENT text must still clear the done mark, got done={done_after_diff}"
    print("2. apply_task_edit still clears the done mark when the text actually changes")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 2: task_done_callback / finish_evening (via toggle_task_done)
    # deleted ALL pool items matching the task's text by exact match, not
    # just the one actually associated with this task -- no break in the
    # fallback-by-text loop.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Вика', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    today2 = datetime.now(bot.get_user_tz(bot.get_user(uid2))).date().isoformat()

    # Two independent pool items with the same text (no dedup on add).
    bot.add_pool_task(uid2, "Купить молоко")
    bot.add_pool_task(uid2, "Купить молоко")
    assert len(bot.get_pool_tasks(uid2)) == 2, "sanity: two independent duplicate pool items"

    # Task set manually (typed the same text) -- no _pool_link_ tie.
    ctx4 = FakeCtx()
    msg4 = FakeMsg(uid2)
    await bot.apply_task_edit(msg4, ctx4, uid2, "focus", "Купить молоко")

    upd4 = FakeUpdate(uid2)
    upd4.callback_query.data = "task_done_focus"
    await bot.task_done_callback(upd4, FakeCtx())

    remaining = bot.get_pool_tasks(uid2)
    assert len(remaining) == 1, \
        f"marking ONE task done must remove only ONE matching pool duplicate, got {len(remaining)} left"
    print("3. task_done_callback deletes only ONE matching pool duplicate, not all of them")

    print("\nALL TASK-POOL-INTEGRITY TESTS PASSED")


asyncio.run(main())
