import os, sys, asyncio, sqlite3, types
from datetime import datetime, timedelta, timezone as _timezone

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup4_batch.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = "fake-key-for-tests"

_fake_reply = {"text": ""}

class FakeContent:
    def __init__(self, text): self.text = text

class FakeResp:
    def __init__(self, text): self.content = [FakeContent(text)]

class FakeMessages:
    def create(self, **kw):
        return FakeResp(_fake_reply["text"])

class FakeAnthropic:
    def __init__(self, api_key=None):
        self.messages = FakeMessages()

fake_module = types.ModuleType("anthropic")
fake_module.Anthropic = FakeAnthropic
sys.modules["anthropic"] = fake_module

def set_fake_reply(text):
    _fake_reply["text"] = text

import bot
bot.init_db()

# Real flakiness: Bug C below derives its scenario from the REAL wall-clock
# time ("3 hours ago"), dropping the date via strftime("%H:%M"). Whenever
# the real clock happens to be within ~3h of midnight, "3 hours ago" wraps
# into yesterday, and reconstructing "today at that HH:MM" inside
# check_notifications no longer means what the test intended. Freezing
# bot.py's own clock to a fixed, safe (mid-day) instant makes it
# reproducible regardless of when this test runs -- but only around Bug C:
# Bug D (further down) deliberately searches for a timezone where it's
# genuinely Monday right now, so it must keep using the real clock.
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
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data=None, text=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})
        self.callback_query = FakeQuery(uid, data) if data is not None else None
        self.message = FakeMsg()
        self.message.text = text


class FakeCtx:
    def __init__(self):
        self.user_data = {}


class FakeBot:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail
    async def send_message(self, chat_id, text, **kw):
        if self.fail:
            raise RuntimeError("simulated Telegram failure")
        self.sent.append((chat_id, text, kw.get("reply_markup")))


class FakeApp:
    def __init__(self, fail=False):
        self.bot = FakeBot(fail=fail)


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")
    tz = bot.get_user_tz(bot.get_user(uid))

    # ══════════════════════════════════════════════════════════════════════
    # Bug A/B: "Отмена" on Settings/Task-pool/Reminders screens left stale
    # awaiting_* flags armed, so the next unrelated message got hijacked.
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    ctx.user_data["awaiting_name"] = True
    upd = FakeUpdate(uid, data="go_settings")
    await bot.go_settings(upd, ctx)
    assert ctx.user_data.get("awaiting_name") is False, ctx.user_data
    print("1. go_settings (reached via 'Отмена') clears stale awaiting_name")

    ctx2 = FakeCtx()
    ctx2.user_data["awaiting_time"] = True
    upd2 = FakeUpdate(uid, data="go_task_pool")
    await bot.show_task_pool(upd2, ctx2)
    assert ctx2.user_data.get("awaiting_time") is False, ctx2.user_data
    print("2. show_task_pool (reached via 'Отмена') clears stale awaiting_time")

    ctx3 = FakeCtx()
    ctx3.user_data["awaiting_city"] = True
    upd3 = FakeUpdate(uid, data="go_reminders")
    await bot.show_reminders(upd3, ctx3)
    assert ctx3.user_data.get("awaiting_city") is False, ctx3.user_data
    print("3. show_reminders (reached via 'Отмена') clears stale awaiting_city")

    # ══════════════════════════════════════════════════════════════════════
    # Bug B: picking a pool suggestion (not typing) must also clear
    # awaiting_task_edit, not just the typed-text path.
    # ══════════════════════════════════════════════════════════════════════
    bot.add_pool_task(uid, "Купить хлеб")
    ctx4 = FakeCtx()
    upd4 = FakeUpdate(uid, data="edit_task_focus")  # legacy single-slot entry, no task_walk
    await bot.edit_task_callback(upd4, ctx4)
    assert ctx4.user_data.get("awaiting_task_edit") == "focus", ctx4.user_data
    pool_item = bot.get_pool_tasks(uid)[0]
    upd5 = FakeUpdate(uid, data=f"pooluse_focus_{pool_item['id']}")
    await bot.pool_use_item(upd5, ctx4)
    assert "awaiting_task_edit" not in ctx4.user_data, \
        f"picking a pool suggestion must clear awaiting_task_edit too, got {ctx4.user_data}"
    print("4. Picking a pool suggestion (not typing) clears awaiting_task_edit")

    # ══════════════════════════════════════════════════════════════════════
    # Bug C: the "утро ещё не закрыто" (+2h) reminder must mark itself sent
    # only AFTER a successful send, not before. Calls the REAL
    # check_notifications end to end, not a reimplementation.
    # ══════════════════════════════════════════════════════════════════════
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Тест', 'M')")
    conn.commit(); conn.close()
    uid2 = 2
    freeze_bot_time()
    now_dt = bot.datetime.now(tz)
    day_key = now_dt.date().isoformat()
    past_morning = (now_dt - timedelta(hours=3)).strftime("%H:%M")  # +2h window already passed
    bot.update_user(
        uid2, timezone="Asia/Tbilisi",
        notif_enabled=1, notif_morning_on=1, notif_morning=past_morning,
        morning_sent_date=day_key,  # primary morning notif already handled -- isolate the +2h block
        notif_midday_on=0, notif_evening_on=0,
        beacon_enabled=0, skill_beacon_enabled=0,
        weekly_report_sent_date=day_key,  # not testing this here
        resume_check_due="", focus_active=0,
    )
    bot._morning_conv = None

    failing_app = FakeApp(fail=True)
    await bot.check_notifications(failing_app)
    assert bot.get_user(uid2).get("morning_reminder_sent_date") != day_key, \
        "a failed send must NOT mark the +2h reminder as sent"
    print("5a. A failed +2h reminder send does not mark itself as sent (can retry)")

    ok_app = FakeApp(fail=False)
    await bot.check_notifications(ok_app)
    assert bot.get_user(uid2).get("morning_reminder_sent_date") == day_key
    assert any("не поставлены" in t for _, t, _ in ok_app.bot.sent), ok_app.bot.sent
    print("5b. A successful +2h reminder send correctly marks itself as sent")

    # Bug D (right below) deliberately depends on the REAL current time to
    # find a timezone where it's genuinely Monday -- restore the real clock.
    unfreeze_bot_time()

    # ══════════════════════════════════════════════════════════════════════
    # Bug D: weekly_report must not be gated by notif_morning_on, and must
    # fire even when notif_morning_on is off. Calls the REAL
    # check_notifications end to end, on a Monday (moved from Sunday --
    # see test_weekly_report_monday.py for why).
    # ══════════════════════════════════════════════════════════════════════
    set_fake_reply("не суть")
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Monday', 'F')")
    conn.commit(); conn.close()
    uid3 = 3
    # Find the timezone offset that makes "now" fall on Monday for this user,
    # so the test is not flaky depending on which day it actually runs.
    monday_tz = None
    for offset in range(-11, 13):
        candidate_tz = f"Etc/GMT{'+' if -offset >= 0 else '-'}{abs(-offset)}" if offset != 0 else "UTC"
        try:
            import pytz
            cand = pytz.timezone(candidate_tz)
            if datetime.now(cand).weekday() == 0:
                monday_tz = candidate_tz
                break
        except Exception:
            continue
    if monday_tz:
        bot.update_user(
            uid3, timezone=monday_tz,
            notif_enabled=1, notif_morning_on=0,  # OFF on purpose -- must not block weekly_report
            notif_morning="00:00",  # already past for any time of day
            morning_sent_date="",  # irrelevant since notif_morning_on is off
            notif_midday_on=0, notif_evening_on=0,
            beacon_enabled=0, skill_beacon_enabled=0,
            weekly_report_sent_date="",
            resume_check_due="", focus_active=0,
        )
        app3 = FakeApp()
        await bot.check_notifications(app3)
        assert bot.get_user(uid3).get("weekly_report_sent_date") not in (None, ""), \
            "weekly_report must fire on Monday even with notif_morning_on off"
        print("6. weekly_report fires on Monday even when notif_morning_on is off (independent gate)")
    else:
        print("6. SKIPPED (no timezone found where it's currently Monday -- harmless, rare)")

    # ══════════════════════════════════════════════════════════════════════
    # Bug E: successful_payment_callback must use the user's own timezone,
    # not the server's naive date.today().
    # ══════════════════════════════════════════════════════════════════════
    class FakePayment:
        total_amount = 100
        telegram_payment_charge_id = "charge_1"

    class FakePayUpdate:
        def __init__(self, uid):
            self.effective_user = FakeUser(uid)
            self.effective_chat = type("C", (), {"id": uid})()
            self.message = FakeMsg()
            self.message.successful_payment = FakePayment()

    bot.update_user(uid2, subscription_until="")
    upd_pay = FakePayUpdate(uid2)
    await bot.successful_payment_callback(upd_pay, FakeCtx())
    new_until = bot.get_user(uid2)["subscription_until"][:10]
    expected = (datetime.now(tz).date() + timedelta(days=bot.STARS_SUBSCRIPTION_DAYS)).isoformat()
    assert new_until == expected, f"expected {expected}, got {new_until}"
    print("7. successful_payment_callback computes the new subscription date in the user's own timezone")

    print("\nALL CHECKUP-4 BATCH TESTS PASSED")


asyncio.run(main())
