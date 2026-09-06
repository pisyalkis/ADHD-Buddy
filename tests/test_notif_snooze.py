import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_notif_snooze.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
    async def edit_text(self, text, **kw): return self
    async def reply_text(self, text, **kw): return self


class FakeQuery:
    def __init__(self, uid, data):
        self.from_user = FakeUser(uid); self.message = FakeMsg(uid); self.data = data
    async def answer(self, *a, **kw): self.answered = (a, kw)


class FakeUpdate:
    def __init__(self, uid, data):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


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


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request: a single "🔕 Выключить такие уведомления" button turned
    # the whole notification type off FOREVER -- but the irritation is
    # usually situational ("устал сегодня, не насовсем"), not a decision to
    # disable the feature permanently. disable_notif_row now offers both a
    # "😴 Не сегодня" snooze (skips just today, feature stays on) and the
    # existing "🔕 Насовсем" permanent toggle.
    # ══════════════════════════════════════════════════════════════════════

    # 1. disable_notif_row offers both buttons.
    row = bot.disable_notif_row("morning")
    flat = [(b.text, b.callback_data) for b in row]
    assert ("😴 Не сегодня", "snooze_notif_morning") in flat, flat
    assert ("🔕 Насовсем", "disable_notif_morning") in flat, flat
    print("1. disable_notif_row offers both a snooze and a permanent-disable button")

    # 2. Tapping snooze sets notif_snooze_<kind> to today (user's own tz),
    #    WITHOUT touching the permanent enabled column.
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi", notif_morning_on=1)

    ctx = FakeCtx()
    upd = FakeUpdate(uid, "snooze_notif_morning")
    await bot.snooze_notification_type(upd, ctx)

    user = bot.get_user(uid)
    today_iso = datetime.now(bot.get_user_tz(user)).date().isoformat()
    assert user.get("notif_snooze_morning") == today_iso, user.get("notif_snooze_morning")
    assert int(user.get("notif_morning_on")) == 1, "snoozing must NOT permanently disable the notification type"
    print("2. snooze_notification_type stamps today's date without touching the permanent on/off column")

    # 3. check_notifications skips today's morning notification for a
    #    snoozed user, WITHOUT marking it as sent (must resume tomorrow).
    # notif_morning is set a few minutes in the past (not 00:00) so the
    # unrelated "missed morning by +2h" reminder doesn't also fire and
    # pollute this assertion. midday/evening explicitly disabled too --
    # this test's real run time can land past their own default trigger
    # times (13:00/21:00), which would otherwise also fire and pollute
    # app.bot.sent with an unrelated message (real flakiness, not this
    # test's concern -- it only cares about morning + its snooze).
    soon_past = (datetime.now(bot.get_user_tz(user)) - timedelta(minutes=5)).strftime("%H:%M")
    bot.update_user(
        uid, notif_enabled=1, notif_morning_on=1, notif_morning=soon_past,
        notif_midday_on=0, notif_evening_on=0,
        morning_sent_date="", notif_snooze_morning=today_iso,
        # Also independent of morning's own snooze (see _process_user_notifications)
        # and can land on a real Monday during a run -- mark it already sent so
        # it doesn't pollute this assertion, same as the guard above for midday/evening.
        weekly_report_sent_date=today_iso,
    )
    app = FakeApp()
    await bot.check_notifications(app)
    assert not app.bot.sent, f"a snoozed morning notification must not be sent, got: {app.bot.sent}"
    assert bot.get_user(uid).get("morning_sent_date") != today_iso, \
        "a snoozed (never actually sent) notification must not be marked as sent for today"
    print("3. check_notifications skips a snoozed morning notification and doesn't mark it as sent")

    # 4. Sanity/regression: WITHOUT the snooze, the same user gets the
    #    morning notification as before.
    bot.update_user(uid, notif_snooze_morning="", morning_sent_date="")
    app2 = FakeApp()
    await bot.check_notifications(app2)
    assert app2.bot.sent, "sanity: without a snooze, the morning notification must still fire normally"
    print("4. Without an active snooze, the morning notification still fires normally (no regression)")

    # 5. send_task_beacon/send_skill_beacon also respect their own snooze.
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Вика', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    now2 = datetime.now(bot.get_user_tz(bot.get_user(uid2)))
    today_iso2 = now2.date().isoformat()
    bot.save_diary(uid2, "morning", {"focus": "Написать отчёт"}, for_date=today_iso2)
    bot.update_user(
        uid2,
        beacon_enabled=1, beacon_interval=1, beacon_start="00:00", beacon_end="23:59",
        beacon_last_sent=(now2 - timedelta(hours=5)).isoformat(),
        notif_snooze_beacon=today_iso2,
        skill_beacon_enabled=1, beacon_types="breathing",
        skill_beacon_mode="interval", skill_beacon_interval=1,
        skill_beacon_last_sent=(now2 - timedelta(hours=5)).isoformat(),
        notif_snooze_skillbeacon=today_iso2,
    )
    app3 = FakeApp()
    user2 = bot.get_user(uid2)
    await bot.send_task_beacon(app3, user2)
    await bot.send_skill_beacon(app3, user2)
    assert not app3.bot.sent, f"snoozed beacons must not send anything, got: {app3.bot.sent}"
    print("5. send_task_beacon/send_skill_beacon respect their own notif_snooze_* fields")

    print("\nALL NOTIF-SNOOZE TESTS PASSED")


asyncio.run(main())
