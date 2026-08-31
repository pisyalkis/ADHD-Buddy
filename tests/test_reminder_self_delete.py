import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_reminder_self_delete.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeMsg:
    _next_id = [55000]
    def __init__(self):
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        m = FakeMsg()
        self.sent.append((chat_id, text, m.message_id))
        return m


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


def scheduled_for(chat_id, message_id):
    conn = sqlite3.connect(bot.DB_PATH)
    row = conn.execute(
        "SELECT delete_at FROM scheduled_deletions WHERE chat_id=? AND message_id=?",
        (chat_id, message_id)
    ).fetchone()
    conn.close()
    return row


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")

    now = datetime.now(bot.get_user_tz(bot.get_user(uid)))
    past = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S")
    bot.add_reminder(uid, "Позвонить в банк", past, recur=None)
    bot.add_reminder(uid, "Выпить воды", past, recur=None)

    app = FakeApp()
    await bot.send_due_reminders(app, bot.get_user(uid), now)

    assert len(app.bot.sent) == 2, app.bot.sent
    mid1, mid2 = app.bot.sent[0][2], app.bot.sent[1][2]

    # ══════════════════════════════════════════════════════════════════════
    # Real request: fired reminders must self-delete after a TTL of silence,
    # but firing one must NOT delete the other's still-unread message (no
    # same-channel replacement like send_tracked_notification does).
    # ══════════════════════════════════════════════════════════════════════
    row1 = scheduled_for(uid, mid1)
    row2 = scheduled_for(uid, mid2)
    assert row1 is not None, "first fired reminder must be scheduled for self-deletion"
    assert row2 is not None, "second fired reminder must be scheduled for self-deletion"
    assert mid1 != mid2
    print("1. Both independently-fired reminders get their OWN self-deletion schedule (neither wipes the other)")

    print("\nALL REMINDER-SELF-DELETE TESTS PASSED")


asyncio.run(main())
