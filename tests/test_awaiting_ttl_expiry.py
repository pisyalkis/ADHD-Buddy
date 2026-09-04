import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_awaiting_ttl_expiry.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id, text):
        self.chat_id = chat_id
        self.message_id = 1
        self.text = text
        self.from_user = FakeUser(chat_id)
    async def edit_text(self, text, **kw): return self
    async def reply_text(self, text, **kw): return self


class FakeUpdate:
    def __init__(self, uid, text):
        self.message = FakeMsg(uid, text)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)
        self.callback_query = None


class FakeBot:
    async def send_message(self, *a, **kw): pass


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeBot()


def long_ago_iso():
    return (datetime.now() - timedelta(seconds=bot.INACTIVE_SCREEN_TTL_SEC + 60)).isoformat()


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Bug: awaiting_task_edit/awaiting_pool_add/awaiting_reminder_add/
    # awaiting_reminder_edit are set alongside a prompt message that
    # self-deletes after INACTIVE_SCREEN_TTL_SEC of silence -- but nothing
    # cleared the flag itself when that happened. A stale flag would
    # silently swallow the user's next, totally unrelated message (hours
    # or days later) into the wrong handler. Worst for
    # awaiting_reminder_add: a failed parse reinstalls the flag with no
    # staleness check at all, so it self-perpetuates on every random reply
    # that isn't recognized as a date/time.
    # ══════════════════════════════════════════════════════════════════════

    # 1. awaiting_task_edit: expired flag must NOT capture the next message
    #    as a task-edit answer -- check the actual side effect (the morning
    #    diary's "focus" field), not just that the flag ends up cleared
    #    (which happens either way: honored-and-consumed, or expired-and-
    #    cleared both pop the flag -- only the diary write distinguishes them).
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    ctx = FakeCtx()
    ctx.user_data["awaiting_task_edit"] = "focus"
    ctx.user_data["awaiting_task_edit_set_at"] = long_ago_iso()
    upd = FakeUpdate(uid, "Купить хлеб")
    await bot.handle_text(upd, ctx)
    assert bot.get_diary(uid, "morning", today).get("focus") != "Купить хлеб", \
        "an expired awaiting_task_edit must not be honored -- the message must not land in the task field"
    print("1. Expired awaiting_task_edit does not swallow an unrelated message into the task field")

    # 2. awaiting_pool_add: same -- check the pool itself, not just the flag.
    ctx2 = FakeCtx()
    ctx2.user_data["awaiting_pool_add"] = True
    ctx2.user_data["awaiting_pool_add_set_at"] = long_ago_iso()
    upd2 = FakeUpdate(uid, "Просто болтаю с ботом")
    await bot.handle_text(upd2, ctx2)
    pool_texts = [item["text"] for item in bot.get_pool_tasks(uid)]
    assert "Просто болтаю с ботом" not in pool_texts, \
        f"an expired awaiting_pool_add must not add the message to the pool, got pool: {pool_texts}"
    print("2. Expired awaiting_pool_add does not add the unrelated message to the pool")

    # 3. awaiting_reminder_edit: same.
    ctx3 = FakeCtx()
    ctx3.user_data["awaiting_reminder_edit"] = 42
    ctx3.user_data["awaiting_reminder_edit_set_at"] = long_ago_iso()
    upd3 = FakeUpdate(uid, "Привет, как дела?")
    await bot.handle_text(upd3, ctx3)
    assert not ctx3.user_data.get("awaiting_reminder_edit"), \
        f"an expired awaiting_reminder_edit must be cleared, got: {ctx3.user_data}"
    print("3. Expired awaiting_reminder_edit is cleared")

    # 4. The worst case: awaiting_reminder_add's self-reinstalling retry
    #    trap. Set it long ago, send unparseable text -- with the bug, this
    #    branch would still fire (stale flag honored) AND reinstall itself
    #    forever. With the fix, an already-expired flag must not even be
    #    honored for this first message.
    ctx4 = FakeCtx()
    ctx4.user_data["awaiting_reminder_add"] = True
    ctx4.user_data["awaiting_reminder_add_set_at"] = long_ago_iso()
    upd4 = FakeUpdate(uid, "случайный текст, не время и не дата")
    await bot.handle_text(upd4, ctx4)
    assert not ctx4.user_data.get("awaiting_reminder_add"), \
        f"an expired awaiting_reminder_add must not reinstall itself on a random reply, got: {ctx4.user_data}"
    print("4. Expired awaiting_reminder_add does not re-trap on the next random message")

    # 5. Sanity: a FRESH (not expired) flag must still work exactly as
    #    before -- this fix must not break the normal, in-window case.
    ctx5 = FakeCtx()
    ctx5.user_data["awaiting_pool_add"] = True
    ctx5.user_data["awaiting_pool_add_set_at"] = datetime.now().isoformat()
    upd5 = FakeUpdate(uid, "Купить молоко")
    await bot.handle_text(upd5, ctx5)
    assert ctx5.user_data.get("awaiting_pool_add") is False, \
        f"a fresh, in-window awaiting_pool_add must still be honored normally, got: {ctx5.user_data}"
    pool = bot.get_pool_tasks(uid)
    assert any(item["text"] == "Купить молоко" for item in pool), \
        f"the fresh awaiting_pool_add case must still actually add the pool item, got: {pool}"
    print("5. A fresh, in-window awaiting_pool_add is still honored normally (no regression)")

    print("\nALL AWAITING-TTL-EXPIRY TESTS PASSED")


asyncio.run(main())
