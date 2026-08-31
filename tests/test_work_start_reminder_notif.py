import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_work_start_reminder_notif.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeMsg:
    _next_id = [95000]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1


class FakeBot:
    def __init__(self):
        self.sent = []
        self.deleted = []

    async def send_message(self, chat_id, text, **kw):
        m = FakeMsg(chat_id)
        self.sent.append((chat_id, text, m.message_id))
        return m

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    tz = bot.get_user_tz(bot.get_user(uid))
    today = datetime.now(tz).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Real gap (audit): send_work_start_reminder ("🚪 Пора начинать!") was a
    # raw app.bot.send_message with no tracking or TTL self-delete.
    # ══════════════════════════════════════════════════════════════════════
    past_time = (datetime.now(tz).replace(hour=0, minute=0)).strftime("%H:%M")
    bot.update_user(uid, work_start_time=past_time, work_start_date=today, work_start_sent_date="")
    app = FakeApp()
    user = bot.get_user(uid)
    await bot.send_work_start_reminder(app, user)

    assert len(app.bot.sent) == 1, app.bot.sent
    mid = app.bot.sent[0][2]
    assert bot._get_notif_msg_id(uid, "work_start") == mid, \
        "send_work_start_reminder must now be tracked under channel 'work_start'"
    print("1. send_work_start_reminder is tracked under channel 'work_start'")

    conn = sqlite3.connect(bot.DB_PATH)
    row = conn.execute(
        "SELECT delete_at FROM scheduled_deletions WHERE chat_id=? AND message_id=?", (uid, mid)
    ).fetchone()
    conn.close()
    assert row is not None, "the work-start reminder must be scheduled for self-deletion"
    print("2. It's scheduled to self-delete after the standard silence TTL")

    print("\nALL WORK-START-REMINDER-NOTIF TESTS PASSED")


asyncio.run(main())
