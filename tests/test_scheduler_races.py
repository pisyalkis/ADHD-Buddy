import os, sys, asyncio, sqlite3
from datetime import datetime as real_datetime, timedelta
import pytz

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_scheduler_races.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    def __init__(self):
        self.sent = []
        self._next_id = 1
        self.on_send = None
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        if self.on_send:
            self.on_send()
        mid = self._next_id
        self._next_id += 1
        return FakeMsg(mid)


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug 1 (send_due_reminders): rem was captured once BEFORE the await on
    # send_message -- if the user edits this exact reminder (e.g. turns off
    # repeat) during that await, the reschedule/cancel below used the STALE
    # recur/remind_at, clobbering the just-made edit.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    tz = bot.get_user_tz(bot.get_user(uid))
    now_dt = real_datetime.now(tz)
    due_key = (now_dt - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S")
    bot.add_reminder(uid, "Выпить воды", due_key, recur="daily")
    rem_id = bot.get_due_reminders(uid, now_dt.strftime("%Y-%m-%dT%H:%M:%S"))[0]["id"]

    app = FakeApp()
    # Simulate: while send_message is "in flight", the user edits this same
    # reminder in another update -- turns off the repeat entirely.
    def concurrent_edit():
        bot.update_reminder(uid, rem_id, "Выпить воды", due_key, recur="")
    app.bot.on_send = concurrent_edit

    user = bot.get_user(uid)
    await bot.send_due_reminders(app, user, now_dt)

    survivor = bot.get_reminder(uid, rem_id)
    assert survivor is None, \
        f"the concurrent edit turned off repeat -- reminder must be cancelled (not rescheduled as recurring), got: {survivor}"
    print("1. send_due_reminders honors a concurrent edit made during the send (re-fetches before reschedule/cancel)")

    # Sanity: with NO concurrent edit, a recurring reminder is still
    # correctly rescheduled to the next occurrence (not cancelled).
    bot.add_reminder(uid, "Растяжка", due_key, recur="daily")
    rem_id2 = [r for r in bot.get_due_reminders(uid, now_dt.strftime("%Y-%m-%dT%H:%M:%S")) if r["text"] == "Растяжка"][0]["id"]
    app2 = FakeApp()
    await bot.send_due_reminders(app2, user, now_dt)
    survivor2 = bot.get_reminder(uid, rem_id2)
    assert survivor2 is not None, "an undisturbed recurring reminder must still be rescheduled, not deleted"
    assert survivor2["remind_at"] > due_key, f"must be rescheduled to a future time, got {survivor2}"
    print("2. send_due_reminders still reschedules an undisturbed recurring reminder as before")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 2 (check_notifications): tz/now_dt/now/is_monday were computed
    # from the STALE snapshot (get_all_notif_users(), taken once at the
    # start of the whole tick) BEFORE the per-user get_user(uid) refetch --
    # a user who changes timezone mid-tick still got evaluated against
    # their OLD timezone's "now" for the rest of that tick.
    # ══════════════════════════════════════════════════════════════════════
    class FakeDatetime(real_datetime):
        _fixed = {}
        @classmethod
        def now(cls, tz=None):
            key = getattr(tz, "zone", str(tz))
            if key in cls._fixed:
                return cls._fixed[key]
            return real_datetime.now(tz)

    # Fresh (real, current DB) timezone -> local time is well past the
    # 09:00 morning-notification threshold -> SHOULD fire.
    FakeDatetime._fixed["UTC"] = pytz.UTC.localize(real_datetime(2026, 9, 2, 12, 0, 0))
    # Stale (snapshot) timezone -> local time is before the threshold ->
    # would NOT fire if the buggy code used this snapshot's tz instead.
    stale_tz = pytz.timezone("Etc/GMT+12")
    FakeDatetime._fixed[stale_tz.zone] = stale_tz.localize(real_datetime(2026, 9, 2, 2, 0, 0))

    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Настя', 'F')")
    conn.commit(); conn.close()
    bot.update_user(
        uid2, timezone="UTC", notif_enabled=1, notif_morning="09:00", notif_morning_on=1,
        notif_midday_on=0, notif_evening_on=0, morning_sent_date="",
        created_at="2026-09-02",  # today -- days_since=0, no research milestone
    )

    morning_calls = []
    async def fake_morning_notification(app, u):
        morning_calls.append(u)
        return True
    async def fake_weekly_report(app, u):
        return False

    real_get_all_notif_users = bot.get_all_notif_users
    def stale_get_all_notif_users():
        rows = real_get_all_notif_users()
        return [dict(r, timezone=stale_tz.zone) if r["user_id"] == uid2 else r for r in rows]

    orig_datetime = bot.datetime
    orig_morning = bot.morning_notification
    orig_weekly = bot.weekly_report
    orig_get_all = bot.get_all_notif_users
    bot.datetime = FakeDatetime
    bot.morning_notification = fake_morning_notification
    bot.weekly_report = fake_weekly_report
    bot.get_all_notif_users = stale_get_all_notif_users
    try:
        fake_app = FakeApp()
        await bot.check_notifications(fake_app)
    finally:
        bot.datetime = orig_datetime
        bot.morning_notification = orig_morning
        bot.weekly_report = orig_weekly
        bot.get_all_notif_users = orig_get_all

    assert uid2 in morning_calls, \
        ("the morning notification must fire based on the FRESH (UTC, 12:00 -- past threshold) timezone, "
         "not the stale snapshot's timezone (Etc/GMT+12, 02:00 -- before threshold)")
    print("3. check_notifications evaluates tz/now against the freshly-refetched user, not the stale snapshot")

    print("\nALL SCHEDULER-RACES TESTS PASSED")


asyncio.run(main())
