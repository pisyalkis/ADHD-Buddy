import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_beacon_respects_focus.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        class M:
            message_id = 1
        return M()
    async def delete_message(self, chat_id, message_id):
        pass


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi", beacon_enabled=1, skill_beacon_enabled=1,
                     beacon_start="00:00", beacon_end="23:59", beacon_types="stop")
    # задача на сегодня, ещё не сделана -- иначе send_task_beacon рано вернётся
    now = datetime.now(TBILISI)
    today = now.date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Написать отчёт"}, today)


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-09-05): the focus timer explicitly promises
    # silence during a round ("не отвлекайся — я напишу когда время выйдет
    # 🔕", ttl_seconds=0 on its status message for exactly this reason), but
    # neither beacon ever checked focus_active -- a beacon firing mid-round
    # broke the bot's own explicit promise exactly when interrupting hurts
    # most (focus/hyperfocus).
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    bot.update_user(uid, focus_active=1, focus_end_time=(datetime.now(TBILISI) + timedelta(minutes=20)).isoformat())
    user = bot.get_user(uid)

    app = FakeApp()
    await bot.send_task_beacon(app, user)
    assert not app.bot.sent, f"send_task_beacon must not fire while focus_active=1, got: {app.bot.sent}"
    print("1. send_task_beacon does not fire while a focus round is active")

    app2 = FakeApp()
    await bot.send_skill_beacon(app2, user)
    assert not app2.bot.sent, f"send_skill_beacon must not fire while focus_active=1, got: {app2.bot.sent}"
    print("2. send_skill_beacon does not fire while a focus round is active")

    # 3. Regression: once the round ends (focus_active=0), beacons behave as
    #    before -- not permanently silenced by the new guard.
    bot.update_user(uid, focus_active=0, focus_end_time="")
    user2 = bot.get_user(uid)
    app3 = FakeApp()
    await bot.send_task_beacon(app3, user2)
    assert app3.bot.sent, "send_task_beacon must still fire normally once the focus round has ended"
    print("3. send_task_beacon fires normally again once focus_active is back to 0 (no permanent silencing)")

    print("\nALL BEACON-RESPECTS-FOCUS TESTS PASSED")


asyncio.run(main())
