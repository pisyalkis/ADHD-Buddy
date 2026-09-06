import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_reminder_weekdays.db")
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
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class M:
            message_id = 1
        return M()


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-27): reminders only supported one-off /
    # "every day" / "every <weekday>" -- no "по будням" (Пн-Пт), a common
    # ADHD case (take medication, get ready for work) that shouldn't also
    # fire on weekends. New recur value "weekdays".
    # ══════════════════════════════════════════════════════════════════════

    # 1. next_recur_time("weekdays") skips the weekend: a Friday reminder's
    #    next occurrence is the following Monday, not Saturday.
    friday = datetime(2026, 9, 4, 9, 0)  # a Friday
    assert friday.weekday() == 4, friday.weekday()
    now_after_friday = friday + timedelta(minutes=1)
    next_key = bot.next_recur_time(friday.strftime("%Y-%m-%dT%H:%M:%S"), "weekdays", now_after_friday)
    next_dt = datetime.fromisoformat(next_key)
    assert next_dt.weekday() == 0, next_dt  # Monday
    assert next_dt.date() == (friday + timedelta(days=3)).date(), next_dt
    print("1. next_recur_time('weekdays') skips the weekend -- Friday's next occurrence is Monday")

    # 2. next_recur_time("weekdays") does NOT skip on an ordinary weekday ->
    #    weekday transition (Wednesday -> Thursday).
    wednesday = datetime(2026, 9, 2, 9, 0)
    assert wednesday.weekday() == 2, wednesday.weekday()
    next_key2 = bot.next_recur_time(wednesday.strftime("%Y-%m-%dT%H:%M:%S"), "weekdays", wednesday + timedelta(minutes=1))
    next_dt2 = datetime.fromisoformat(next_key2)
    assert next_dt2.date() == (wednesday + timedelta(days=1)).date(), next_dt2
    print("2. next_recur_time('weekdays') advances by a single day between ordinary weekdays")

    # 3. If the bot was offline and several days were missed (now_dt is far
    #    past remind_at), next_recur_time still lands on the nearest future
    #    WEEKDAY, not a queued-up backlog and not a weekend.
    saturday_now = friday + timedelta(days=1, hours=5)  # Saturday, well past Friday's reminder
    next_key3 = bot.next_recur_time(friday.strftime("%Y-%m-%dT%H:%M:%S"), "weekdays", saturday_now)
    next_dt3 = datetime.fromisoformat(next_key3)
    assert next_dt3.weekday() == 0, next_dt3  # Monday
    assert next_dt3 > saturday_now
    print("3. next_recur_time('weekdays') catches up to the nearest future weekday after a missed gap, never a weekend")

    # 4. recur_label describes "weekdays" as "по будням".
    assert bot.recur_label(friday.strftime("%Y-%m-%dT%H:%M:%S"), "weekdays") == "по будням"
    print("4. recur_label describes 'weekdays' as 'по будням'")

    # 5. End-to-end: a due "weekdays" reminder firing on a Friday reschedules
    #    itself to the following Monday, not Saturday.
    uid = 1
    make_user(uid, "Артем")
    bot.add_reminder(uid, "Принять таблетку", friday.strftime("%Y-%m-%dT%H:%M:%S"), recur="weekdays")
    rem_id = bot.get_reminders(uid)[0]["id"]
    app = FakeApp()
    await bot.send_due_reminders(app, bot.get_user(uid), now_after_friday)
    assert len(app.bot.sent) == 1, app.bot.sent
    rem_after = bot.get_reminder(uid, rem_id)
    rescheduled = datetime.fromisoformat(rem_after["remind_at"])
    assert rescheduled.weekday() == 0, rescheduled
    print("5. send_due_reminders reschedules a fired 'weekdays' reminder to the next weekday (skips the weekend)")

    print("\nALL REMINDER-WEEKDAYS TESTS PASSED")


asyncio.run(main())
