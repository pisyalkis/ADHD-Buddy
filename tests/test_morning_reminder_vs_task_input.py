import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta, timezone as _timezone

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_morning_reminder_vs_task_input.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

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


class FakeMsg:
    _next_id = [61000]

    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1

    async def reply_text(self, text, **kw):
        return FakeMsg(self.chat_id)


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
        self.user_data = {}


def make_user(uid, name, tz_name="Asia/Tbilisi"):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone=tz_name)


def arm_overdue_reminder(uid, now):
    """Same setup as test_morning_reminder_notif.py's check 1: put
    notif_morning far enough in the past that the +2h reminder is due, with
    no tasks in today's diary and no reminder sent yet today."""
    notif_morning_hhmm = (now - timedelta(hours=3)).strftime("%H:%M")
    bot.update_user(
        uid, notif_morning=notif_morning_hhmm, notif_morning_on=1, notif_enabled=1,
        morning_reminder_sent_date="", morning_sent_date=now.date().isoformat(),
        midday_sent_date=now.date().isoformat(), evening_sent_date=now.date().isoformat(),
        weekly_report_sent_date=now.date().isoformat(),
    )


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real live bug report: doing the morning ritual in the afternoon,
    # right after tapping "Да, поставить" and getting the "Задача A ...
    # можешь выбрать из списка дел или написать свою" screen, the "📋
    # Задачи на сегодня ещё не поставлены" reminder fired mid-answer.
    #
    # Root cause: task-setting was deliberately pulled OUT of the morning
    # ConversationHandler ("ритуалы отдельно, задачки отдельно" -- see
    # RESUME_FIELDS comment), so morning_conv_active goes False the moment
    # the ritual's writing/gratitude/child steps finish -- exactly when the
    # task-offer screen (and then _offer_task_input, which sets
    # ctx.user_data["awaiting_task_edit"]) takes over. The reminder's guard
    # never learned about this new, separate flow.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    tz = bot.get_user_tz(bot.get_user(uid))
    freeze_bot_time()
    now = bot.datetime.now(tz)

    # 1. Regression: with nothing special in app.user_data, the overdue
    #    reminder still fires normally (same as test_morning_reminder_notif.py).
    arm_overdue_reminder(uid, now)
    app1 = FakeApp()
    await bot.check_notifications(app1)
    assert len(app1.bot.sent) == 1, app1.bot.sent
    assert "не поставлены" in app1.bot.sent[0][1]
    print("1. The overdue 'задачи не поставлены' reminder still fires normally (no regression)")

    # 2. The bug fix: with awaiting_task_edit set for this user (mid-answer
    #    on the task-offer screen, exactly like the live report), the
    #    reminder must NOT fire -- and must NOT be marked as sent, so it can
    #    still fire later once the user actually finishes or bails out.
    uid2 = 2
    make_user(uid2, "Вика")
    arm_overdue_reminder(uid2, now)
    app2 = FakeApp()
    app2.user_data[uid2] = {"awaiting_task_edit": "focus"}
    await bot.check_notifications(app2)
    assert not app2.bot.sent, \
        f"must not interrupt someone actively answering a task-slot prompt: {app2.bot.sent}"
    assert bot.get_user(uid2).get("morning_reminder_sent_date") != now.date().isoformat(), \
        "must not be marked as sent -- the reminder should still be able to fire later"
    print("2. Being mid-answer on a task-slot prompt (awaiting_task_edit) suppresses the reminder (bug fix)")

    # 3. Once the task-slot prompt is no longer active (flag cleared, e.g.
    #    the user finished or cancelled), the SAME overdue reminder must
    #    still be able to fire on a later tick -- this isn't a permanent
    #    suppression, just a "don't interrupt mid-answer" guard.
    app2.user_data[uid2] = {}
    await bot.check_notifications(app2)
    assert len(app2.bot.sent) == 1, app2.bot.sent
    assert "не поставлены" in app2.bot.sent[0][1]
    print("3. Once awaiting_task_edit clears, the reminder can still fire on a later tick")

    unfreeze_bot_time()
    print("\nALL MORNING-REMINDER-VS-TASK-INPUT TESTS PASSED")


asyncio.run(main())
