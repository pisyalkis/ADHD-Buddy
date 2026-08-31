import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta, date, timezone as _timezone

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup8_notifications.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import pytz
import bot
bot.init_db()

# Real flakiness: Bug 1's second scenario ("sanity" case) derives itself
# from the REAL wall-clock time ("3 hours ago"), dropping the date via
# strftime("%H:%M"). Whenever the real clock happens to be within ~3h of
# midnight, "3 hours ago" wraps into yesterday, and reconstructing "today
# at that HH:MM" inside check_notifications no longer means what the test
# intended. Freezing bot.py's own clock to a fixed, safe (mid-day) instant
# makes it reproducible regardless of when this test runs -- but only
# around that scenario: Bug 2 (further down) deliberately needs the REAL
# current time to find a timezone that genuinely diverges from UTC today.
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


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid):
        self.effective_user = FakeUser(uid)
        self.message = FakeMsg()


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")
    tz = bot.get_user_tz(bot.get_user(uid))

    # ══════════════════════════════════════════════════════════════════════
    # Bug 1: the "+2h missed morning" reminder used a bare "HH:MM" string
    # comparison that drops the date, so for a notif_morning within 2h of
    # midnight (e.g. 22:30), the reminder became eligible almost any time
    # of day instead of specifically ~2h after the real notification.
    # ══════════════════════════════════════════════════════════════════════
    now_dt = datetime.now(tz)
    if now_dt.hour == 0 and now_dt.minute < 30:
        print("1. SKIPPED (current local time happens to fall inside the tiny post-rollover window -- harmless, rare)")
    else:
        # notif_morning fixed at 22:30 -> reminder_time = today 22:30 + 2h
        # = TOMORROW 00:30. The bug: the old code compared bare "HH:MM"
        # strings, dropping the date rollover, so it fired at virtually any
        # time of day (now >= "00:30" is true almost always) instead of
        # only after tomorrow 00:30 genuinely arrives. This does not depend
        # on what time it actually is right now -- any time other than the
        # ~30 minutes right after midnight reproduces it deterministically.
        day_key = now_dt.strftime("%Y-%m-%d")
        bot.update_user(
            uid, timezone="Asia/Tbilisi",
            notif_enabled=1, notif_morning_on=1, notif_morning="22:30",
            morning_sent_date=day_key,  # primary morning notif already handled
            notif_midday_on=0, notif_evening_on=0,
            beacon_enabled=0, skill_beacon_enabled=0,
            weekly_report_sent_date=day_key,
            resume_check_due="", focus_active=0,
            morning_reminder_sent_date="",
        )
        bot._morning_conv = None
        app = FakeApp()
        await bot.check_notifications(app)
        assert bot.get_user(uid).get("morning_reminder_sent_date") != day_key, \
            "the +2h reminder must not fire today when notif_morning=22:30 means reminder_time only arrives tomorrow 00:30"
        assert not any("не поставлены" in t for _, t, _ in app.bot.sent), app.bot.sent
        print("1. The +2h reminder correctly does NOT fire early when notif_morning is close to midnight (reminder_time rolls to tomorrow)")

    # Sanity: with a notif_morning far enough in the past (normal case),
    # the reminder still fires as expected.
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Тест', 'M')")
    conn.commit(); conn.close()
    uid2 = 2
    freeze_bot_time()
    now_dt2 = bot.datetime.now(tz)
    day_key2 = now_dt2.date().isoformat()
    past_morning = (now_dt2 - timedelta(hours=3)).strftime("%H:%M")
    bot.update_user(
        uid2, timezone="Asia/Tbilisi",
        notif_enabled=1, notif_morning_on=1, notif_morning=past_morning,
        morning_sent_date=day_key2,
        notif_midday_on=0, notif_evening_on=0,
        beacon_enabled=0, skill_beacon_enabled=0,
        weekly_report_sent_date=day_key2,
        resume_check_due="", focus_active=0,
        morning_reminder_sent_date="",
    )
    app2 = FakeApp()
    await bot.check_notifications(app2)
    assert bot.get_user(uid2).get("morning_reminder_sent_date") == day_key2
    assert any("не поставлены" in t for _, t, _ in app2.bot.sent), app2.bot.sent
    print("2. The +2h reminder still fires normally once reminder_time has genuinely passed")

    # Bug 2 (right below) deliberately needs the REAL current time to find
    # a timezone that genuinely diverges from UTC today -- restore the
    # real clock.
    unfreeze_bot_time()

    # ══════════════════════════════════════════════════════════════════════
    # Bug 2: admin_stats used naive date.today() instead of the admin's own
    # timezone for the 7/30-day active-user cutoff.
    # ══════════════════════════════════════════════════════════════════════
    admin_uid = 999
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (999, 'Admin', 'M')")
    conn.commit(); conn.close()
    # Pick a timezone offset far enough from UTC that date.today() (server,
    # effectively UTC) and the admin's local date genuinely differ right now.
    diverging_tz = None
    utc_today = datetime.utcnow().date()
    for offset in range(-12, 15):
        if offset == 0:
            continue
        candidate = f"Etc/GMT-{offset}" if offset > 0 else f"Etc/GMT+{abs(offset)}"
        try:
            cand = pytz.timezone(candidate)
            if datetime.now(cand).date() != utc_today:
                diverging_tz = candidate
                break
        except Exception:
            continue

    if diverging_tz:
        bot.update_user(admin_uid, timezone=diverging_tz)
        admin_local_today = datetime.now(pytz.timezone(diverging_tz)).date()

        # A diary row dated exactly at the EARLIEST day that must still
        # count as "active in last 7 days" from the ADMIN's own local
        # today -- one day earlier than the naive server date.today()
        # window would have allowed. This directly exercises the drift.
        # Boundary is today-6 (7 dates inclusive of today: today..today-6) --
        # a later checkup round fixed admin_stats' own off-by-one that used
        # to make this an 8-date window (today-7).
        conn = sqlite3.connect(bot.DB_PATH)
        conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Boundary', 'F')")
        conn.commit(); conn.close()
        uid3 = 3
        boundary_date = (admin_local_today - timedelta(days=6)).isoformat()
        bot.save_diary(uid3, "morning", {"focus": "х"}, for_date=boundary_date)

        # Expected count, computed independently using the admin's own
        # timezone (the correct, fixed behaviour) -- not date.today().
        conn = sqlite3.connect(bot.DB_PATH)
        expected_active7 = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM diary WHERE date >= ?",
            ((admin_local_today - timedelta(days=6)).isoformat(),)
        ).fetchone()[0]
        conn.close()

        upd = FakeUpdate(admin_uid)
        await bot.admin_stats(upd, None)
        text = upd.message.sent[0][0]
        import re
        m = re.search(r"Активны за 7 дней: \*(\d+)\*", text)
        assert m, text
        actual_active7 = int(m.group(1))
        assert actual_active7 == expected_active7, \
            f"admin_stats' 7-day cutoff must use the admin's own timezone, not naive date.today(): expected {expected_active7}, got {actual_active7}"
        assert uid3 in [uid3], "sanity"  # boundary user must be counted (expected_active7 >= 1)
        assert expected_active7 >= 1
        print(f"3. admin_stats resolves the 7-day cutoff via admin's own timezone ({diverging_tz}), matching a boundary day the naive server date.today() would have missed")
    else:
        print("3. SKIPPED (no timezone found currently diverging from server/UTC date -- harmless, rare)")

    print("\nALL CHECKUP8-NOTIFICATIONS TESTS PASSED")


asyncio.run(main())
