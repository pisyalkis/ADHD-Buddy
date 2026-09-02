import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_audit_sweep_batch.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self):
        self.edited = []
        self.sent = []
        self.edit_should_fail = False
    async def edit_text(self, text, **kw):
        if self.edit_should_fail:
            raise Exception("message too old to edit")
        self.edited.append((text, kw.get("reply_markup")))
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
    def __init__(self, uid, data="", text_message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data) if not text_message else None
        self.message = text_message


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def run_edits(uid, handler, data=""):
    upd_ok = FakeUpdate(uid, data=data)
    await handler(upd_ok, FakeCtx())
    assert len(upd_ok.callback_query.message.edited) >= 1, \
        f"{handler.__name__} did not edit the existing message"
    assert len(upd_ok.callback_query.message.sent) == 0, \
        f"{handler.__name__} sent a new message even though editing succeeded"

    upd_fail = FakeUpdate(uid, data=data)
    upd_fail.callback_query.message.edit_should_fail = True
    await handler(upd_fail, FakeCtx())
    assert len(upd_fail.callback_query.message.sent) >= 1, \
        f"{handler.__name__} did not fall back to a new message when editing failed"


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()

    # 1. morning_start's "already filled" recap edits in place.
    bot.update_user(uid, morning_filled_at=datetime.now(bot.get_user_tz(bot.get_user(uid))).isoformat())
    await run_edits(uid, bot.morning_start, "go_morning")
    print("1. morning_start's 'already filled today' recap edits in place, falls back on failure")
    bot.update_user(uid, morning_filled_at="")

    # 3. Stale-item error replies: pool_use_item, evening_plan_use_pool, add_next_task_callback.
    await run_edits(uid, bot.pool_use_item, "pooluse_focus_999999")
    print("3a. pool_use_item's 'item gone' error edits in place, falls back on failure")

    await run_edits(uid, bot.evening_plan_use_pool, "eplanuse_e_a_999999")
    print("3b. evening_plan_use_pool's 'item gone' error edits in place, falls back on failure")

    for k, _ in bot.TASK_FIELDS:
        bot.save_diary(uid, "morning", {kk: "x" for kk, _ in bot.TASK_FIELDS}, for_date=today)
    await run_edits(uid, bot.add_next_task_callback, "add_next_task")
    print("3c. add_next_task_callback's 'all slots full' message edits in place, falls back on failure")
    bot.save_diary(uid, "morning", {}, for_date=today)

    # 4. reminder_edit_start's "no longer active" error.
    await run_edits(uid, bot.reminder_edit_start, "remedit_999999")
    print("4. reminder_edit_start's 'reminder no longer active' error edits in place, falls back on failure")

    # 5. focus_start_callback's "timer already running" message.
    end_dt = datetime.now(bot.get_user_tz(bot.get_user(uid))) + timedelta(minutes=20)
    bot.update_user(uid, focus_active=1, focus_end_time=end_dt.isoformat())
    await run_edits(uid, bot.focus_start_callback, "focus_start_25")
    print("5. focus_start_callback's 'timer already running' message edits in place, falls back on failure")
    bot.update_user(uid, focus_active=0)

    # 6. reminder_add_start's missing-ANTHROPIC_KEY fallback.
    real_key = bot.ANTHROPIC_KEY
    bot.ANTHROPIC_KEY = ""
    await run_edits(uid, bot.reminder_add_start, "rem_add")
    print("6. reminder_add_start's missing-ИИ fallback edits in place, falls back on failure")
    bot.ANTHROPIC_KEY = real_key

    # 7. handle_text's free-text 'reminder'/'add_pool' intents now pass ctx
    # through to create_reminder_and_reply/add_pool_and_reply, so a
    # currently-open ⏰ Напоминания / 📥 Список дел screen gets edited
    # instead of always spawning a new confirmation message.
    import inspect
    src = inspect.getsource(bot.handle_text)
    assert 'create_reminder_and_reply(update.message, uid, routed["remind_at"], routed.get("text") or text, routed.get("recur") or "", ctx=ctx)' in src, \
        "handle_text's free-text reminder intent must pass ctx through"
    assert 'add_pool_and_reply(update.message, uid, routed.get("items") or [text], ctx=ctx)' in src, \
        "handle_text's free-text add_pool intent must pass ctx through"
    print("7. handle_text's free-text reminder/add_pool intents now pass ctx through")

    print("\nALL AUDIT-SWEEP-BATCH TESTS PASSED")


asyncio.run(main())
