import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_work_start_after_walk_and_stale.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [333000]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.reply_calls = []
    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        self.reply_calls.append((text, kw.get("reply_markup"), m))
        return m
    async def edit_text(self, text, **kw):
        return self


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data, message):
        self.callback_query = FakeQuery(uid, data, message)
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})()


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = None


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Walking through slots (✏️ Поставить/изменить задачи) and finishing
    # early via "✅ Готово" must also trigger the deferred work-start prompt
    # -- not just the single-edit/free-text path.
    # ══════════════════════════════════════════════════════════════════════
    finale_msg = FakeMsg(chat_id=uid)
    ctx = FakeCtx()
    await bot.morning_task_offer_yes(FakeUpdate(uid, "morning_tasks_yes", finale_msg), ctx)
    task_screen_msg = finale_msg.reply_calls[0][2]

    await bot.walk_tasks_start(FakeUpdate(uid, "walk_tasks", task_screen_msg), ctx)
    await bot.apply_task_edit(task_screen_msg, ctx, uid, "focus", "Сделать план")
    # Still mid-walk -- the prompt must NOT have fired yet (would interrupt
    # the walk, which continues to the next empty slot).
    assert ctx.user_data.get("ask_work_start_after_tasks"), "flag must survive individual slot saves mid-walk"

    walk_msg = FakeMsg(chat_id=uid)
    await bot.walk_finish_callback(FakeUpdate(uid, "walk_finish", walk_msg), ctx)
    assert any("Во сколько" in c[0] for c in walk_msg.reply_calls), \
        f"finishing the walk early via 'Готово' must trigger the deferred prompt, got {walk_msg.reply_calls}"
    print("1. Finishing the walk via '✅ Готово' triggers the deferred work-start prompt")

    # ══════════════════════════════════════════════════════════════════════
    # Staleness guard: if the offer was made on an earlier day and never
    # acted on, a task set today (for an unrelated reason) must NOT suddenly
    # ask "when do you start work" out of context.
    # ══════════════════════════════════════════════════════════════════════
    ctx2 = FakeCtx()
    ctx2.user_data["ask_work_start_after_tasks"] = "2020-01-01"  # long-stale date
    stale_msg = FakeMsg(chat_id=uid)
    await bot.apply_task_edit(stale_msg, ctx2, uid, "b1", "Что-то не связанное")
    assert not any("Во сколько" in c[0] for c in stale_msg.reply_calls), \
        f"a stale flag from a different day must not fire the prompt, got {stale_msg.reply_calls}"
    assert "ask_work_start_after_tasks" not in ctx2.user_data, "the stale flag must still be cleared"
    print("2. A stale (different-day) flag is discarded instead of firing the prompt out of context")

    print("\nALL WORK-START-AFTER-WALK-AND-STALE TESTS PASSED")


asyncio.run(main())
