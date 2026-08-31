import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_morning_evening_no_self_delete.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        m = type("M", (), {"message_id": 1, "chat_id": chat_id})()
        self.sent.append((chat_id, text))
        return m


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "Давай не будем их удалять" -- morning/evening
    # notifications used to self-delete after 15 minutes of silence
    # (INACTIVE_SCREEN_TTL_SEC, the send_tracked_notification default).
    # They must now stay indefinitely until actually answered.
    # ══════════════════════════════════════════════════════════════════════
    app = FakeApp()
    await bot.morning_notification(app, uid)
    mid = bot._get_notif_msg_id(uid, "morning")
    assert mid is not None

    conn = sqlite3.connect(bot.DB_PATH)
    row = conn.execute(
        "SELECT * FROM scheduled_deletions WHERE chat_id=? AND message_id=?", (uid, mid)
    ).fetchone()
    conn.close()
    assert row is None, "the morning notification must NOT be scheduled for self-deletion"
    print("1. morning_notification no longer schedules a self-deletion")

    app2 = FakeApp()
    await bot.evening_notification(app2, uid)
    mid2 = bot._get_notif_msg_id(uid, "evening")
    assert mid2 is not None

    conn = sqlite3.connect(bot.DB_PATH)
    row2 = conn.execute(
        "SELECT * FROM scheduled_deletions WHERE chat_id=? AND message_id=?", (uid, mid2)
    ).fetchone()
    conn.close()
    assert row2 is None, "the evening notification must NOT be scheduled for self-deletion"
    print("2. evening_notification no longer schedules a self-deletion")

    print("\nALL MORNING-EVENING-NO-SELF-DELETE TESTS PASSED")


asyncio.run(main())
