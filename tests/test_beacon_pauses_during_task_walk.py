import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_beacon_pauses_during_task_walk.db")
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
        class M:
            message_id = 1
            chat_id = 0
        return M()
    async def send_animation(self, chat_id, animation, **kw):
        self.sent.append((chat_id, "<animation>"))
        class M:
            message_id = 1
            chat_id = 0
        return M()


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()
        self.user_data = {}


def setup_user(uid, tz="Asia/Tbilisi"):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, 'Артем', 'M')", (uid,))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone=tz)
    now = datetime.now(bot.pytz.timezone(tz))
    today_iso = now.date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Написать отчёт"}, for_date=today_iso)
    bot.update_user(
        uid,
        beacon_enabled=1, beacon_interval=1,
        beacon_start="00:00", beacon_end="23:59",
        beacon_last_sent=(now - timedelta(hours=5)).isoformat(),
        skill_beacon_enabled=1, beacon_types="breathing",
        skill_beacon_mode="interval", skill_beacon_interval=1,
        skill_beacon_last_sent=(now - timedelta(hours=5)).isoformat(),
    )


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug: send_task_beacon/send_skill_beacon/midday_notification fire on
    # their own schedule regardless of what the user is doing right now.
    # walk_tasks_start's step-by-step task walk edits ONE message in place
    # (see _render_walk_step/STEP_MSG_STALE_SEC) -- if a beacon lands as a
    # brand new message WHILE that walk is in progress, the walk's own
    # screen visually "crawls" up behind the newly arrived message, even
    # though the walk itself keeps working underneath. Real feedback
    # (Victoria): "менюшка с задачами уползла на два сообщения выше".
    # ══════════════════════════════════════════════════════════════════════

    # 1. task_walk active -> beacons/midday must NOT send anything this tick.
    uid = 1
    setup_user(uid)
    app = FakeApp()
    app.user_data[uid] = {"task_walk": True}
    user = bot.get_user(uid)

    await bot.send_task_beacon(app, user)
    await bot.send_skill_beacon(app, user)
    midday_result = await bot.midday_notification(app, uid)

    assert not app.bot.sent, f"no background notification should fire while task_walk is active, got: {app.bot.sent}"
    assert midday_result is False, \
        "midday_notification must return False (not sent) while paused, so it retries later instead of being marked sent"
    print("1. send_task_beacon/send_skill_beacon/midday_notification all stay silent while task_walk is active")

    # 2. Sanity/regression: WITHOUT an active task_walk, the same user in
    #    the same state must still get the normal notifications as before.
    uid2 = 2
    setup_user(uid2)
    app2 = FakeApp()
    app2.user_data[uid2] = {}
    user2 = bot.get_user(uid2)

    await bot.send_task_beacon(app2, user2)
    assert app2.bot.sent, "sanity: without an active task_walk, send_task_beacon must still fire normally"
    print("2. Without an active task_walk, send_task_beacon still fires normally (no regression)")

    print("\nALL BEACON-PAUSES-DURING-TASK-WALK TESTS PASSED")


asyncio.run(main())
