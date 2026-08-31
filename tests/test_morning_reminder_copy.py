import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta, timezone as _timezone

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_morning_reminder_copy.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

# Real flakiness: this test derives its scenario from the REAL wall-clock
# time ("3 hours ago"), dropping the date via strftime("%H:%M"). Whenever
# the real clock happens to be within ~3h of midnight, "3 hours ago" wraps
# into yesterday, and reconstructing "today at that HH:MM" inside
# check_notifications no longer means what the test intended. Freezing
# bot.py's own clock to a fixed, safe (mid-day) instant makes the scenario
# reproducible regardless of when this test runs.
_REAL_BOT_DATETIME = bot.datetime

class _FrozenDateTime(_REAL_BOT_DATETIME):
    _FROZEN_UTC = _REAL_BOT_DATETIME(2026, 1, 15, 8, 0, 0, tzinfo=_timezone.utc)  # noon in Asia/Tbilisi (UTC+4)
    @classmethod
    def now(cls, tz=None):
        return cls._FROZEN_UTC.astimezone(tz) if tz is not None else cls._FROZEN_UTC.replace(tzinfo=None)

bot.datetime = _FrozenDateTime


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeBot:
    def __init__(self):
        self.sent = []
        self.deleted = []
    async def send_message(self, chat_id, text, **kw):
        class _M:
            message_id = 12345
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        return _M()
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
    tz_name = "Asia/Tbilisi"
    now = bot.datetime.now(bot.pytz.timezone(tz_name))
    notif_morning_hhmm = (now - timedelta(hours=3)).strftime("%H:%M")
    bot.update_user(
        uid, timezone=tz_name, notif_morning=notif_morning_hhmm, notif_morning_on=1, notif_enabled=1,
        morning_reminder_sent_date="", morning_sent_date=now.date().isoformat(),
        midday_sent_date=now.date().isoformat(), evening_sent_date=now.date().isoformat(),
        weekly_report_sent_date=now.date().isoformat(),
    )

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: the old text ("☀️ Утро ещё не закрыто") implied the
    # WHOLE ritual wasn't done, even though the actual trigger condition is
    # only "no tasks set yet" -- misleading a user who'd already done the
    # full soft ritual into tapping a button that restarted it. New copy
    # names the real gap (tasks) and gives a reason, and its button goes
    # straight to 📋 Задачи instead of routing through morning_start.
    # ══════════════════════════════════════════════════════════════════════
    app = FakeApp()
    await bot.check_notifications(app)
    assert len(app.bot.sent) == 1, app.bot.sent
    text, kb = app.bot.sent[0][1], app.bot.sent[0][2]
    assert "не закрыто" not in text, text
    assert "не поставлены" in text, text
    buttons = [b for row in kb.inline_keyboard for b in row]
    assert any(b.callback_data == "go_tasks" for b in buttons), buttons
    assert not any(b.callback_data == "go_morning" for b in buttons), \
        "the reminder's button should no longer route through morning_start"
    print("1. The +2h reminder now names the actual gap (tasks) and links straight to 📋 Задачи")


asyncio.run(main())
