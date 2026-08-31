import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_morning_notif_skips_if_filled.db")
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
        self.sent.append((chat_id, text))
        return type("M", (), {"message_id": 1, "chat_id": chat_id})()
    async def delete_message(self, chat_id, message_id):
        pass


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = bot.datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Real complaint: "Я заполнил утро сам, до уведомления. Но сейчас мне
    # всё равно пришло уведомление" -- morning_notification had no guard
    # analogous to evening_notification's "if any(evening.values()): return".
    # ══════════════════════════════════════════════════════════════════════
    app = FakeApp()
    result = await bot.morning_notification(app, uid)
    assert result is True
    assert len(app.bot.sent) == 1, "with an empty morning diary, the notification must send normally"
    print("1. morning_notification sends normally when morning is genuinely empty")

    # Filling morning via the task-setting path (📋 Задачи), NOT the full
    # ritual -- e.g. exactly what the user described doing "before the
    # notification" -- must also suppress it, not just finish_morning.
    bot.save_diary(uid, "morning", {"focus": "Купить билеты"}, for_date=today)
    app2 = FakeApp()
    result2 = await bot.morning_notification(app2, uid)
    assert result2 is True, "must report success (so it's marked as handled for today), not retry"
    assert app2.bot.sent == [], \
        f"morning already has content -- the notification must be skipped entirely, got {app2.bot.sent}"
    print("2. morning_notification is skipped once morning has any content, however it got filled")

    print("\nALL MORNING-NOTIF-SKIPS-IF-FILLED TESTS PASSED")


asyncio.run(main())
