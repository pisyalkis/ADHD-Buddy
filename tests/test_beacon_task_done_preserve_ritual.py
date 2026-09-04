import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_beacon_task_done_preserve_ritual.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeBot:
    async def send_message(self, *a, **kw):
        return FakeMsg(a[0] if a else kw.get("chat_id"))
    async def delete_message(self, *a, **kw):
        pass


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
    async def edit_text(self, text, **kw): return self
    async def reply_text(self, text, **kw): return self
    async def edit_reply_markup(self, **kw): return self


class FakeQuery:
    def __init__(self, uid, data):
        self.from_user = FakeUser(uid); self.message = FakeMsg(uid); self.data = data
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeBot()


class FakeConvHandler:
    def __init__(self):
        self._conversations = {}


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug: beacon_technique_done/task_done_callback called the FULL
    # clear_awaiting_flags(ctx, update), which -- per its own docstring --
    # also unconditionally pops the active morning/evening ConversationHandler
    # state. Both are quick-tap actions on a beacon/reminder message that
    # arrives independently of whatever the user is currently doing --
    # tapping "✅ Сделал(а)" on a skill beacon, or a task checkbox on a
    # midday/resume-check notification, while genuinely in the middle of
    # the evening ritual (e.g. E_ACH) silently cancelled that ritual, even
    # though the user never tried to leave it.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender, buddy_name) VALUES (1, 'Артем', 'M', '')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Написать отчёт"}, for_date=today)

    fake_evening_conv = FakeConvHandler()
    conv_key = (uid, uid)
    fake_evening_conv._conversations[conv_key] = bot.E_ACH  # actively mid-ritual
    bot._evening_conv = fake_evening_conv
    try:
        ctx = FakeCtx()
        ctx.user_data["awaiting_feedback"] = True  # some stale flag that SHOULD still be cleared

        upd = FakeUpdate(uid, "beacon_done")
        await bot.beacon_technique_done(upd, ctx)

        assert conv_key in fake_evening_conv._conversations, \
            "beacon_technique_done must NOT cancel an active evening ritual conversation"
        assert ctx.user_data.get("awaiting_feedback") is False, \
            "beacon_technique_done must still clear stale ctx.user_data awaiting_* flags"
        print("1. beacon_technique_done preserves an active evening-ritual conversation, still clears awaiting_* flags")

        ctx2 = FakeCtx()
        ctx2.user_data["awaiting_feedback"] = True
        upd2 = FakeUpdate(uid, "task_done_focus")
        await bot.task_done_callback(upd2, ctx2)

        assert conv_key in fake_evening_conv._conversations, \
            "task_done_callback must NOT cancel an active evening ritual conversation"
        assert ctx2.user_data.get("awaiting_feedback") is False, \
            "task_done_callback must still clear stale ctx.user_data awaiting_* flags"
        print("2. task_done_callback preserves an active evening-ritual conversation, still clears awaiting_* flags")
    finally:
        bot._evening_conv = None

    print("\nALL BEACON-TASK-DONE-PRESERVE-RITUAL TESTS PASSED")


asyncio.run(main())
