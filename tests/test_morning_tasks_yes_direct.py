import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_morning_tasks_yes_direct.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [95000]

    def __init__(self, chat_id=1, message_id=None):
        self.chat_id = chat_id
        self.message_id = message_id if message_id is not None else FakeMsg._next_id[0]
        if message_id is None:
            FakeMsg._next_id[0] += 1
        self.reply_calls = []

    async def reply_text(self, text, **kw):
        self.reply_calls.append((text, kw.get("reply_markup")))
        return FakeMsg(self.chat_id)


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
        self.message = None


class FakeBot:
    def __init__(self):
        self.edits = []  # (chat_id, message_id, text)

    async def edit_message_text(self, chat_id, message_id, text, **kw):
        self.edits.append((chat_id, message_id, text))


class FakeCtx:
    def __init__(self, bot_):
        self.user_data = {}
        self.bot = bot_


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real live bug report: after the morning ritual, "📋 Поставить задачи
    # на сегодня?" offers "Да, поставить"/"Не сейчас". Tapping "Да" landed
    # on the generic 📋 Задачи OVERVIEW screen ("задачи ещё не заданы —
    # можно поставить здесь") -- an extra, confusing step, since the user
    # had JUST explicitly said "yes, let's set them". Fixed: "Да, поставить"
    # now jumps straight into the same step-by-step walk (Задача A first)
    # as the "✏️ Поставить/изменить задачи" button already used elsewhere,
    # taking over the SAME message in place.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    today = datetime.now(TBILISI).date().isoformat()

    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    ritual_offer_screen = FakeMsg(chat_id=uid)  # the "Поставить задачи?" message with Да/Не сейчас

    upd = FakeUpdate(uid, "morning_tasks_yes", ritual_offer_screen)
    await bot.morning_task_offer_yes(upd, ctx)

    # 1. No generic "задачи ещё не заданы" overview screen -- the very
    #    first thing shown must be the Task A prompt itself.
    assert not ritual_offer_screen.reply_calls, \
        f"must not send a separate overview screen via reply_text, got: {ritual_offer_screen.reply_calls}"
    assert fbot.edits, "must edit the tapped ritual-offer message directly into the Task A prompt"
    last_text = fbot.edits[-1][2]
    assert "задачи ещё не заданы" not in last_text.lower(), \
        f"must not show the generic 'not set yet' overview text: {last_text}"
    assert bot.TASK_LABELS.get("focus", "A") in last_text or "A" in last_text or "Задача" in last_text, last_text
    print("1. 'Да, поставить' jumps straight to the Task A prompt, no intermediate overview screen")

    # 2. It takes over the SAME message the button was tapped on (in place),
    #    not a brand-new one -- same single-message discipline as the rest
    #    of the walk (see test_walk_single_message.py).
    assert fbot.edits[-1][1] == ritual_offer_screen.message_id, \
        f"must edit the SAME message the offer was on, got edits: {fbot.edits}"
    assert ctx.user_data.get("walk_step_msg_id") == ritual_offer_screen.message_id
    print("2. It edits the SAME message in place -- no new message spawned")

    # 3. The deferred "ask work start time" flag is still armed with
    #    today's date, exactly as before this fix.
    assert ctx.user_data.get("ask_work_start_after_tasks") == today, ctx.user_data
    print("3. ask_work_start_after_tasks is still armed with today's date (no regression)")

    # 4. Regression: the actual walk mechanics underneath (task_walk mode,
    #    awaiting_task_edit for slot 'focus') are wired up correctly --
    #    typing text now should apply to Task A, not get lost.
    assert ctx.user_data.get("task_walk") is True
    user_text_msg = FakeMsg(chat_id=uid)
    await bot.apply_task_edit(user_text_msg, ctx, uid, "focus", "Сделать отчёт")
    morning = bot.get_diary(uid, "morning", today)
    assert morning.get("focus") == "Сделать отчёт", morning
    print("4. The walk underneath still works correctly -- typed text lands on Task A")

    print("\nALL MORNING-TASKS-YES-DIRECT TESTS PASSED")


asyncio.run(main())
