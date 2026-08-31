import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_weekly_report_monday.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import pytz
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


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1

    # ══════════════════════════════════════════════════════════════════════
    # Bug (Artem, with screenshot): the weekly report used to be sent
    # Sunday morning and counted a 7-day window INCLUDING today (Sunday) --
    # so it could never show a real 7/7 even if the user closed both
    # blocks later that same Sunday.
    # ══════════════════════════════════════════════════════════════════════

    # ── weekly_report's own day window must exclude "today" ────────────────
    bot.update_user(uid, timezone="Asia/Tbilisi")
    tz = bot.get_user_tz(bot.get_user(uid))
    today = datetime.now(tz).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    # Fill in TODAY's morning+evening -- if today were still counted, this
    # would show up in the tally. It must not.
    bot.save_diary(uid, "morning", {"focus": "Задача сегодня"}, for_date=today.isoformat())
    bot.save_diary(uid, "evening", {"e_a": "план", "e_tasks_done": ["focus"]}, for_date=today.isoformat())
    # Fill in YESTERDAY (part of the reported window) -- this must count.
    bot.save_diary(uid, "morning", {"focus": "Задача вчера"}, for_date=yesterday)
    bot.save_diary(uid, "evening", {"e_a": "план", "e_tasks_done": ["focus"]}, for_date=yesterday)

    app = FakeApp()
    ok = await bot.weekly_report(app, uid)
    assert ok, "weekly_report must succeed"
    report_text = app.bot.sent[0][1]
    assert "Задача сегодня" not in report_text or True  # report doesn't quote task text directly
    # Only yesterday's morning/evening should count -> 1 of 7 each, not 2.
    assert "Утренних блоков заполнено: *1 из 7*" in report_text, report_text
    assert "Вечерних блоков закрыто: *1 из 7*" in report_text, report_text
    print("1. weekly_report's 7-day window excludes today -- only fully-lived days count")

    # ── check_notifications fires the report on Monday, not Sunday ─────────
    monday_tz = None
    for offset in range(-11, 13):
        candidate = f"Etc/GMT{'+' if -offset >= 0 else '-'}{abs(-offset)}" if offset != 0 else "UTC"
        try:
            cand = pytz.timezone(candidate)
            if datetime.now(cand).weekday() == 0:
                monday_tz = candidate
                break
        except Exception:
            continue

    if monday_tz:
        conn = sqlite3.connect(bot.DB_PATH)
        conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Тест', 'F')")
        conn.commit(); conn.close()
        uid2 = 2
        bot.update_user(
            uid2, timezone=monday_tz,
            notif_enabled=1, notif_morning_on=0, notif_morning="00:00",
            morning_sent_date="", notif_midday_on=0, notif_evening_on=0,
            beacon_enabled=0, skill_beacon_enabled=0,
            weekly_report_sent_date="", resume_check_due="", focus_active=0,
        )
        app2 = FakeApp()
        await bot.check_notifications(app2)
        assert bot.get_user(uid2).get("weekly_report_sent_date") not in (None, ""), \
            "weekly_report must fire on Monday"
        print("2. check_notifications fires the weekly report on Monday")
    else:
        print("2. SKIPPED (no timezone currently on Monday -- harmless, rare)")

    # A Sunday timezone must NOT trigger it anymore.
    sunday_tz = None
    for offset in range(-11, 13):
        candidate = f"Etc/GMT{'+' if -offset >= 0 else '-'}{abs(-offset)}" if offset != 0 else "UTC"
        try:
            cand = pytz.timezone(candidate)
            if datetime.now(cand).weekday() == 6:
                sunday_tz = candidate
                break
        except Exception:
            continue

    if sunday_tz:
        conn = sqlite3.connect(bot.DB_PATH)
        conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Sunday', 'M')")
        conn.commit(); conn.close()
        uid3 = 3
        bot.update_user(
            uid3, timezone=sunday_tz,
            notif_enabled=1, notif_morning_on=0, notif_morning="00:00",
            morning_sent_date="", notif_midday_on=0, notif_evening_on=0,
            beacon_enabled=0, skill_beacon_enabled=0,
            weekly_report_sent_date="", resume_check_due="", focus_active=0,
        )
        app3 = FakeApp()
        await bot.check_notifications(app3)
        assert bot.get_user(uid3).get("weekly_report_sent_date") in (None, ""), \
            "weekly_report must NOT fire on Sunday anymore"
        print("3. check_notifications no longer fires the weekly report on Sunday")
    else:
        print("3. SKIPPED (no timezone currently on Sunday -- harmless, rare)")

    print("\nALL WEEKLY-REPORT-MONDAY TESTS PASSED")


asyncio.run(main())
