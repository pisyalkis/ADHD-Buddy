import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup9_notifications.db")
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
        self.sent.append((chat_id, text, kw.get("reply_markup")))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
        self.answered = False
    async def answer(self, *a, **kw):
        self.answered = True


class FakeUpdate:
    def __init__(self, uid, data="go_focus"):
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})
        self.effective_message = FakeMsg()
        self.callback_query = FakeQuery(uid, data)
        self.message = None
        self.pre_checkout_query = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Тест', 'M')")
    conn.commit(); conn.close()
    tz_name = "Asia/Tbilisi"

    # ══════════════════════════════════════════════════════════════════════
    # Bug (9th checkup): check_notifications' per-tick `user` snapshot goes
    # stale mid-loop -- if midday_notification fires and writes
    # midday_sent_date to the DB, send_task_beacon's own anti-dup guard
    # (which reads user["midday_sent_date"]) was reading the pre-update,
    # stale value, and fired a near-duplicate "what are you doing?" message
    # seconds after the midday chekin, in that one tick.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    now_dt = datetime.now(bot.get_user_tz(bot.update_user(uid, timezone=tz_name) or bot.get_user(uid)))
    day_key = now_dt.date().isoformat()
    bot.update_user(
        uid, timezone=tz_name,
        notif_enabled=1, notif_morning_on=0, notif_morning="00:00", morning_sent_date=day_key,
        notif_midday_on=1, notif_midday=now_dt.strftime("%H:%M"), midday_sent_date="",
        notif_evening_on=0,
        beacon_enabled=1, beacon_interval=1, beacon_start="00:00", beacon_end="23:59",
        beacon_last_sent="", morning_filled_at="",
        skill_beacon_enabled=0,
        weekly_report_sent_date=day_key, resume_check_due="", focus_active=0,
    )
    bot.save_diary(uid, "morning", {"focus": "Сделать отчёт"}, for_date=day_key)
    app = FakeApp()
    await bot.check_notifications(app)
    texts = [t for _, t, _ in app.bot.sent]
    midday_count = sum(1 for t in texts if "Дневной чекин" in t)
    beacon_count = sum(1 for t in texts if "Маячок" in t)
    assert midday_count == 1, texts
    assert beacon_count == 0, \
        f"the task beacon must not fire in the same tick right after the midday chekin was just sent, got: {texts}"
    print("1. send_task_beacon no longer duplicates the midday check-in in the same tick (fresh user re-fetch)")

    # ══════════════════════════════════════════════════════════════════════
    # Bug (9th checkup): access_gate blocked a callback_query without ever
    # answering it -- the tapped button stayed in Telegram's spinner state
    # client-side until its own timeout, since the real handler for that
    # callback_data never ran (ApplicationHandlerStop fired first).
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    bot.update_user(uid2, timezone=tz_name)
    # Force an expired access status regardless of trial length.
    import bot as botmod
    orig = botmod.get_access_status
    botmod.get_access_status = lambda user: "expired"
    try:
        upd = FakeUpdate(uid2, data="go_focus")  # not in ACCESS_GATE_EXEMPT_CALLBACKS
        ctx = FakeCtx()
        was_stopped = False
        try:
            await bot.access_gate(upd, ctx)
        except bot.ApplicationHandlerStop:
            was_stopped = True
        assert was_stopped, "access_gate must still block the expired user"
        assert upd.callback_query.answered, \
            "access_gate must answer the callback_query it blocks, or the tapped button spins forever client-side"
    finally:
        botmod.get_access_status = orig
    print("2. access_gate now answers the callback_query before blocking, no more stuck spinner")

    print("\nALL CHECKUP9-NOTIFICATIONS TESTS PASSED")


asyncio.run(main())
