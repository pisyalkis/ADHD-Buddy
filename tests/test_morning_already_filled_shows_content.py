import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_morning_already_filled_shows_content.db")
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
        self.message_id = 555
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
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
        self.message = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Real request: tapping ☀️ Утро in the menu after the ritual is already
    # done for today should show what was ACTUALLY written (writing/
    # gratitude/child) instead of the generic "go set tasks" line -- tasks
    # live only in 📋 Задачи now.
    # ══════════════════════════════════════════════════════════════════════
    bot.save_diary(uid, "morning", {
        "focus": "Написать отчёт",  # a task -- must NOT show up on this screen
        "writing": "Голова была занята дедлайном",
        "gratitude": "Благодарен за отпуск на выходных",
        "child": "Ты справляешься лучше, чем кажется",
    }, for_date=today)
    bot.update_user(uid, morning_filled_at=datetime.now(bot.get_user_tz(bot.get_user(uid))).isoformat())

    ctx = FakeCtx()
    msg = FakeMsg(chat_id=uid)
    await bot.morning_start(FakeUpdate(uid, data="go_morning", message=msg), ctx)

    assert len(msg.sent) == 1
    text = msg.sent[0][0]
    assert "Написать отчёт" not in text, f"tasks must not appear on this screen, got: {text}"
    assert "Голова была занята дедлайном" in text, text
    assert "Благодарен за отпуск на выходных" in text, text
    assert "Ты справляешься лучше, чем кажется" in text, text
    print("1. Re-opening ☀️ Утро after the ritual shows the actual writing/gratitude/child, no tasks")

    # ══════════════════════════════════════════════════════════════════════
    # If the soft ritual questions were skipped/disabled entirely (quick
    # morning), the screen must not look broken/empty.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Ника', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    bot.save_diary(uid2, "morning", {"focus": "Задача"}, for_date=today)
    bot.update_user(uid2, morning_filled_at=datetime.now(bot.get_user_tz(bot.get_user(uid2))).isoformat())
    ctx2 = FakeCtx()
    msg2 = FakeMsg(chat_id=uid2)
    await bot.morning_start(FakeUpdate(uid2, data="go_morning", message=msg2), ctx2)
    text2 = msg2.sent[0][0]
    assert "пропущены" in text2, text2
    print("2. When the soft ritual answers are empty, the screen shows a friendly note instead of looking empty")

    print("\nALL MORNING-ALREADY-FILLED-SHOWS-CONTENT TESTS PASSED")


asyncio.run(main())
