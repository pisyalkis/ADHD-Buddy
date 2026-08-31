import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_beacon_notif_single_message.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [51000]
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

    async def send_animation(self, **kw):
        class _A:
            animation = None
        return _A()


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
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "маячки и другие уведомления" -- delete the previous
    # notification of the SAME channel when a new one fires, delete it when
    # the user answers, and self-delete after 15 min of silence.
    # ══════════════════════════════════════════════════════════════════════
    app = FakeApp()
    bot.update_user(
        uid, beacon_enabled=1, beacon_interval=2, beacon_start="00:00", beacon_end="23:59",
    )
    bot.save_diary(uid, "morning", {"focus": "Сделать отчёт"}, for_date=today)

    await bot.send_task_beacon(app, bot.get_user(uid))
    assert len(app.bot.sent) == 1
    first_beacon_mid = app.bot.sent[-1][2]
    tracked = bot._get_notif_msg_id(uid, "task_beacon")
    assert tracked == first_beacon_mid
    print("1. First task-beacon send is tracked under channel 'task_beacon'")

    # Trigger a second beacon tick without answering the first (force past
    # the interval gate by resetting beacon_last_sent to the distant past).
    bot.update_user(uid, beacon_last_sent="")
    await bot.send_task_beacon(app, bot.get_user(uid))
    assert len(app.bot.sent) == 2
    second_beacon_mid = app.bot.sent[-1][2]
    assert (uid, first_beacon_mid) in app.bot.deleted, \
        "the previous, unanswered task beacon must be deleted before the new one is sent"
    assert bot._get_notif_msg_id(uid, "task_beacon") == second_beacon_mid
    print("2. A second task-beacon tick deletes the previous unanswered one before sending the new one")

    # Answering via midday_kb (shared with midday_notification) edits the
    # SAME message into the response, in place -- rather than deleting it
    # and sending a brand new one.
    beacon_screen = FakeMsg(chat_id=uid); beacon_screen.message_id = second_beacon_mid
    ctx = FakeCtx(app.bot)
    upd = FakeUpdate(uid, "mid_resting", beacon_screen)
    await bot.midday_callback(upd, ctx)
    assert (uid, second_beacon_mid) not in app.bot.deleted, \
        "answering the task beacon must edit it in place, not delete it"
    assert beacon_screen.edited, "the beacon message must be edited into the response"
    assert bot._get_notif_msg_id(uid, "task_beacon") is None
    print("3. Answering the task beacon (mid_resting) edits it in place and clears tracking")

    # ══════════════════════════════════════════════════════════════════════
    # Skill beacon: same replace-on-resend + delete-on-answer behavior.
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(
        uid, skill_beacon_enabled=1, beacon_types="stop,breathing",
        beacon_start="00:00", beacon_end="23:59", skill_beacon_last_sent="", beacon_rotation_idx="0",
    )
    await bot.send_skill_beacon(app, bot.get_user(uid))
    skill_mid = bot._get_notif_msg_id(uid, "skill_beacon")
    assert skill_mid is not None
    print("4. Skill beacon is tracked under channel 'skill_beacon'")

    skill_screen = FakeMsg(chat_id=uid); skill_screen.message_id = skill_mid
    upd2 = FakeUpdate(uid, "beacon_technique_done", skill_screen)
    await bot.beacon_technique_done(upd2, ctx)
    assert (uid, skill_mid) in app.bot.deleted
    assert bot._get_notif_msg_id(uid, "skill_beacon") is None
    print("5. Answering the skill beacon (beacon_technique_done) deletes it and clears tracking")

    # ══════════════════════════════════════════════════════════════════════
    # Midday notification: same replace-on-resend behavior (independent
    # channel from task_beacon, even though they share midday_kb).
    # ══════════════════════════════════════════════════════════════════════
    await bot.midday_notification(app, uid)
    midday_mid1 = bot._get_notif_msg_id(uid, "midday")
    assert midday_mid1 is not None
    await bot.midday_notification(app, uid)
    midday_mid2 = bot._get_notif_msg_id(uid, "midday")
    assert (uid, midday_mid1) in app.bot.deleted
    assert midday_mid2 != midday_mid1
    print("6. A second midday notification deletes the previous unanswered one (independent of task_beacon)")

    midday_screen = FakeMsg(chat_id=uid); midday_screen.message_id = midday_mid2
    upd3 = FakeUpdate(uid, "mid_ok", midday_screen)
    await bot.midday_callback(upd3, ctx)
    assert (uid, midday_mid2) not in app.bot.deleted
    assert midday_screen.edited, "the midday notification must be edited into the response, not deleted"
    assert bot._get_notif_msg_id(uid, "midday") is None
    print("7. Answering the midday notification (mid_ok) edits it in place and clears tracking")

    # ══════════════════════════════════════════════════════════════════════
    # Morning notification: answered by tapping "☀️ Заполнить утро" (go_morning).
    # A fresh uid (not uid=1, whose morning diary already has "focus" set
    # from the task-beacon setup above) -- morning_notification now skips
    # itself entirely once morning has anything in it (see below), so this
    # part needs a genuinely empty morning to exercise the send-path at all.
    # ══════════════════════════════════════════════════════════════════════
    uid_morning = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Третий', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid_morning, timezone="Asia/Tbilisi")

    await bot.morning_notification(app, uid_morning)
    morning_mid = bot._get_notif_msg_id(uid_morning, "morning")
    assert morning_mid is not None
    print("8. Morning notification is tracked under channel 'morning'")

    morning_screen = FakeMsg(chat_id=uid_morning); morning_screen.message_id = morning_mid
    upd4 = FakeUpdate(uid_morning, "go_morning", morning_screen)
    ctx2 = FakeCtx(app.bot)
    await bot.morning_start(upd4, ctx2)
    assert (uid_morning, morning_mid) not in app.bot.deleted, \
        "tapping '☀️ Заполнить утро' must edit the morning notification in place, not delete it"
    assert morning_screen.edited, "the morning notification must be edited into the ritual's first step"
    assert bot._get_notif_msg_id(uid_morning, "morning") is None
    print("9. Tapping '☀️ Заполнить утро' edits the morning notification in place and clears tracking")

    # ══════════════════════════════════════════════════════════════════════
    # Evening notification: answered by tapping "🌙 Закрыть день" (go_evening).
    # ══════════════════════════════════════════════════════════════════════
    await bot.evening_notification(app, uid)
    evening_mid = bot._get_notif_msg_id(uid, "evening")
    assert evening_mid is not None
    print("10. Evening notification is tracked under channel 'evening'")

    evening_screen = FakeMsg(chat_id=uid); evening_screen.message_id = evening_mid
    upd5 = FakeUpdate(uid, "go_evening", evening_screen)
    ctx3 = FakeCtx(app.bot)
    await bot.evening_start(upd5, ctx3)
    assert (uid, evening_mid) not in app.bot.deleted, \
        "tapping '🌙 Закрыть день' must edit the evening notification in place, not delete it"
    assert evening_screen.edited, "the evening notification must be edited into the ritual's first greeting"
    assert bot._get_notif_msg_id(uid, "evening") is None
    print("11. Tapping '🌙 Закрыть день' edits the evening notification in place and clears tracking")

    # ══════════════════════════════════════════════════════════════════════
    # 15-minute silence: every tracked notification schedules its own
    # self-deletion via the existing DB-backed queue (survives restarts).
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, beacon_last_sent="", midday_sent_date="")
    await bot.send_task_beacon(app, bot.get_user(uid))
    latest_mid = bot._get_notif_msg_id(uid, "task_beacon")
    conn = sqlite3.connect(bot.DB_PATH)
    row = conn.execute(
        "SELECT delete_at FROM scheduled_deletions WHERE chat_id=? AND message_id=?", (uid, latest_mid)
    ).fetchone()
    conn.close()
    assert row is not None, "a sent notification must be scheduled for self-deletion"
    delta = (datetime.fromisoformat(row[0]) - datetime.now()).total_seconds()
    assert 890 <= delta <= 910, f"expected ~900s (15 min) TTL, got {delta}"
    print("12. Every sent notification is scheduled to self-delete after 15 minutes of silence")

    print("\nALL BEACON-NOTIF-SINGLE-MESSAGE TESTS PASSED")


asyncio.run(main())
