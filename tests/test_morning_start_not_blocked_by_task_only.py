import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_morning_start_not_blocked_by_task_only.db")
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
    # Real report (screenshot): responded to the "цели не поставлены"
    # reminder, set a task there (apply_task_edit -- this ALSO stamps
    # user.morning_filled_at, for the task beacon's benefit). Then tried to
    # open ☀️ Утро for the actual ritual (soft practices) -- got "Утро уже
    # записано сегодня" / "Мягкие практики были пропущены", with only a
    # Menu button, and no way to actually do the ritual. morning_start was
    # using the SAME morning_filled_at field for both "a task was set" and
    # "the ritual is done", which are not the same thing.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # Simulate: responded to the goal reminder, set task A via apply_task_edit.
    ctx = FakeCtx()
    msg = FakeMsg(uid)
    await bot.apply_task_edit(msg, ctx, uid, "focus", "Отправить письмо")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    assert (bot.get_user(uid).get("morning_filled_at") or "")[:10] == today, \
        "sanity: apply_task_edit stamps morning_filled_at (for the task beacon)"
    morning = bot.get_diary(uid, "morning", today)
    assert not any(k in morning for k in bot.SOFT_RITUAL_KEYS), \
        "sanity: setting a task must not touch the soft-ritual keys at all"

    # Now try to open ☀️ Утро -- must actually start the ritual, not show
    # the "already recorded" recap.
    upd = FakeUpdate(uid)
    ctx2 = FakeCtx()
    await bot.morning_start(upd, ctx2)
    rendered = upd.callback_query.message.edited + upd.callback_query.message.sent
    all_text = "\n".join(t for t, kw in rendered)
    assert "Утро уже записано сегодня" not in all_text, \
        f"setting only a task must NOT block the morning ritual, got: {all_text}"
    assert "Доброе утро" in all_text, \
        f"morning_start must actually greet and start the ritual, got: {all_text}"
    print("1. Setting a task via apply_task_edit no longer blocks ☀️ Утро from starting")

    # ══════════════════════════════════════════════════════════════════════
    # Sanity: once the ritual (or an explicit skip within it) is genuinely
    # done, morning_start must still correctly show the recap -- this is
    # not a regression on the original behavior, only the false positive
    # from task-only actions is fixed.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Прошёл', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    today2 = datetime.now(bot.get_user_tz(bot.get_user(uid2))).date().isoformat()
    bot.save_diary(uid2, "morning", {"writing": "", "gratitude": "", "child": ""}, for_date=today2)

    upd2 = FakeUpdate(uid2)
    ctx3 = FakeCtx()
    await bot.morning_start(upd2, ctx3)
    rendered2 = upd2.callback_query.message.edited + upd2.callback_query.message.sent
    all_text2 = "\n".join(t for t, kw in rendered2)
    assert "Утро уже записано сегодня" in all_text2, \
        f"a genuinely completed (even all-skipped) ritual must still show the recap, got: {all_text2}"
    print("2. A genuinely completed ritual (even fully skipped) still shows the recap as before")

    print("\nALL MORNING-START-NOT-BLOCKED-BY-TASK-ONLY TESTS PASSED")


asyncio.run(main())
