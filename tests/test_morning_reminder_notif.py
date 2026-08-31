import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta, timezone as _timezone

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_morning_reminder_notif.db")
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
# check_notifications no longer means what the test intended -- same class
# of bug as the real "reminder_time rolls to tomorrow" case bot.py itself
# guards against. Freezing bot.py's own clock to a fixed, safe (mid-day)
# instant makes the scenario reproducible regardless of when this test runs.
_REAL_BOT_DATETIME = bot.datetime

class _FrozenDateTime(_REAL_BOT_DATETIME):
    _FROZEN_UTC = _REAL_BOT_DATETIME(2026, 1, 15, 8, 0, 0, tzinfo=_timezone.utc)  # noon in Asia/Tbilisi (UTC+4)
    @classmethod
    def now(cls, tz=None):
        return cls._FROZEN_UTC.astimezone(tz) if tz is not None else cls._FROZEN_UTC.replace(tzinfo=None)

def freeze_bot_time():
    bot.datetime = _FrozenDateTime

def unfreeze_bot_time():
    bot.datetime = _REAL_BOT_DATETIME


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [61000]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.edited = []

    async def reply_text(self, text, **kw):
        return FakeMsg(self.chat_id)

    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))


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


class FakeCtx:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    tz_name = "Asia/Tbilisi"
    bot.update_user(uid, timezone=tz_name)
    tz = bot.get_user_tz(bot.get_user(uid))
    freeze_bot_time()
    now = bot.datetime.now(tz)

    # ══════════════════════════════════════════════════════════════════════
    # Real request: extend the "+2h, утро ещё не закрыто" inline reminder
    # (previously untouched, plain app.bot.send_message with no tracking)
    # with the same single-message-per-channel behavior as the other
    # notifications -- but with a 30-minute TTL instead of the usual 15.
    # ══════════════════════════════════════════════════════════════════════
    notif_morning_hhmm = (now - timedelta(hours=3)).strftime("%H:%M")  # so reminder_time (+2h) is already past
    bot.update_user(
        uid, notif_morning=notif_morning_hhmm, notif_morning_on=1, notif_enabled=1,
        morning_reminder_sent_date="", morning_sent_date=now.date().isoformat(),
        midday_sent_date=now.date().isoformat(), evening_sent_date=now.date().isoformat(),
        weekly_report_sent_date=now.date().isoformat(),
    )
    app = FakeApp()
    await bot.check_notifications(app)

    assert len(app.bot.sent) == 1, app.bot.sent
    text = app.bot.sent[0][1]
    assert "не поставлены" in text, text
    reminder_mid = app.bot.sent[0][2]
    assert bot._get_notif_msg_id(uid, "morning_reminder") == reminder_mid
    print("1. The +2h 'задачи не поставлены' reminder is now tracked under channel 'morning_reminder'")

    conn = sqlite3.connect(bot.DB_PATH)
    row = conn.execute(
        "SELECT delete_at FROM scheduled_deletions WHERE chat_id=? AND message_id=?", (uid, reminder_mid)
    ).fetchone()
    conn.close()
    assert row is not None
    delta = (datetime.fromisoformat(row[0]) - bot.datetime.now()).total_seconds()
    assert 1790 <= delta <= 1810, f"expected ~1800s (30 min) TTL, got {delta}"
    print("2. It self-deletes after 30 minutes (not the usual 15 the other channels use)")

    # Tapping "📋 Поставить задачи" on it (the actual button on this
    # reminder -- see check_notifications) must edit it in place into the
    # tasks screen and clear tracking -- not delete it and send a new one.
    reminder_screen = FakeMsg(chat_id=uid); reminder_screen.message_id = reminder_mid
    ctx = FakeCtx(app.bot)
    upd = FakeUpdate(uid, "go_tasks", reminder_screen)
    await bot.show_tasks(upd, ctx)
    assert (uid, reminder_mid) not in app.bot.deleted, \
        "tapping '📋 Поставить задачи' on the +2h reminder must edit it in place, not delete it"
    assert reminder_screen.edited, "the reminder must be edited into the tasks screen"
    assert bot._get_notif_msg_id(uid, "morning_reminder") is None
    print("3. Tapping '📋 Поставить задачи' edits the +2h reminder in place into the tasks screen and clears its tracking")

    unfreeze_bot_time()
    print("\nALL MORNING-REMINDER-NOTIF TESTS PASSED")


asyncio.run(main())
