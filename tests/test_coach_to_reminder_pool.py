import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coach_to_reminder_pool.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [301000]
    def __init__(self, chat_id, text=None):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.text = text
        self.reply_calls = []

    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        self.reply_calls.append((text, kw.get("reply_markup")))
        return m

    async def edit_text(self, text, **kw):
        self.text = text
        return self


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=None, message=None, text_message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message) if data is not None else None
        self.message = text_message


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        m = FakeMsg(chat_id)
        self.sent.append((chat_id, text, m.message_id))
        return m
    async def edit_message_text(self, chat_id, message_id, text, **kw):
        pass


class FakeCtx:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-29): the coach's single concrete piece
    # of advice used to end with only a "◀️ Меню" button -- turning it into
    # a reminder or a pool item required manually retyping it in another
    # section. Two new buttons reuse the EXISTING creation machinery
    # (add_pool_and_reply / parse_reminder_request + create_reminder_and_reply)
    # instead of duplicating it.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    advice = "Возьми лист бумаги и напиши первую фразу отчёта — 5 минут."

    # 1. coach_to_pool adds the coach's own last reply straight into the
    #    task pool, no retyping, via the same add_pool_and_reply used
    #    elsewhere for add_pool.
    ctx = FakeCtx(FakeBot())
    ctx.user_data["coach_last_reply"] = advice
    msg = FakeMsg(uid)
    update = FakeUpdate(uid, data="coach_to_pool", message=msg)
    await bot.coach_to_pool(update, ctx)
    pool = bot.get_pool_tasks(uid)
    assert any(t["text"] == advice for t in pool), pool
    print("1. coach_to_pool adds the coach's own advice text into the task pool")

    # 2. coach_to_reminder arms awaiting_reminder_add + stashes the advice as
    #    coach_reminder_seed, WITHOUT requiring the user to retype the advice.
    uid2 = 2
    make_user(uid2, "Вика")
    ctx2 = FakeCtx(FakeBot())
    ctx2.user_data["coach_last_reply"] = advice
    msg2 = FakeMsg(uid2)
    update2 = FakeUpdate(uid2, data="coach_to_reminder", message=msg2)
    await bot.coach_to_reminder(update2, ctx2)
    assert ctx2.user_data.get("awaiting_reminder_add") is True
    assert ctx2.user_data.get("coach_reminder_seed") == advice
    print("2. coach_to_reminder arms awaiting_reminder_add and stashes the coach's advice as a seed")

    # 3. Typing just the TIME (no content) combines with the seed before
    #    calling parse_reminder_request -- verified by monkeypatching it to
    #    capture what text it actually received (real ANTHROPIC_KEY unset in
    #    tests, so parse_reminder_request itself can't run for real here).
    captured = {}
    async def fake_parse(text, now_dt):
        captured["text"] = text
        return ("2026-09-10T09:00:00", advice, "")
    orig_parse = bot.parse_reminder_request
    bot.parse_reminder_request = fake_parse
    try:
        time_only_msg = FakeMsg(uid2, text="через 20 минут")
        update3 = FakeUpdate(uid2, text_message=time_only_msg)
        await bot.handle_text(update3, ctx2)
    finally:
        bot.parse_reminder_request = orig_parse

    assert captured.get("text") == f"через 20 минут: {advice}", captured
    assert ctx2.user_data.get("coach_reminder_seed") is None, \
        "the seed must be consumed (popped) once used, not left lingering"
    reminders = bot.get_reminders(uid2)
    assert any(r["text"] == advice for r in reminders), reminders
    print("3. Typing only the time combines it with the coach's seed advice before parsing, and the reminder is created")

    # 4. If parsing fails, the seed is put BACK so the user isn't forced to
    #    start over from the coach conversation.
    uid3 = 3
    make_user(uid3, "Игорь")
    ctx3 = FakeCtx(FakeBot())
    ctx3.user_data["coach_last_reply"] = advice
    msg3 = FakeMsg(uid3)
    update4 = FakeUpdate(uid3, data="coach_to_reminder", message=msg3)
    await bot.coach_to_reminder(update4, ctx3)

    async def fake_parse_fail(text, now_dt):
        return None
    bot.parse_reminder_request = fake_parse_fail
    try:
        bad_msg = FakeMsg(uid3, text="блабла")
        update5 = FakeUpdate(uid3, text_message=bad_msg)
        await bot.handle_text(update5, ctx3)
    finally:
        bot.parse_reminder_request = orig_parse

    assert ctx3.user_data.get("awaiting_reminder_add") is True, \
        "a failed parse must re-arm awaiting_reminder_add for a retry"
    assert ctx3.user_data.get("coach_reminder_seed") == advice, \
        "a failed parse must restore the seed, not lose the coach's advice"
    print("4. A failed parse re-arms the retry and restores the coach's advice seed instead of losing it")

    # 5. clear_awaiting_and_cancel_ritual/clear_awaiting_flags clean up both
    #    new keys -- no stale coach_last_reply/coach_reminder_seed leaking
    #    into an unrelated later flow.
    ctx4 = FakeCtx(FakeBot())
    ctx4.user_data["coach_last_reply"] = advice
    ctx4.user_data["coach_reminder_seed"] = advice
    bot.clear_awaiting_flags(ctx4)
    assert "coach_last_reply" not in ctx4.user_data
    assert "coach_reminder_seed" not in ctx4.user_data
    print("5. clear_awaiting_flags cleans up coach_last_reply/coach_reminder_seed")

    print("\nALL COACH-TO-REMINDER-POOL TESTS PASSED")


asyncio.run(main())
