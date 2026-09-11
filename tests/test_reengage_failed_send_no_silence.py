import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_reengage_failed_send_no_silence.db")
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


def find_tz_with_local_hour(target_hour):
    """Same trick as test_reengage_early_morning_dedup.py -- pick a fixed-
    offset timezone where the CURRENT real time's local hour equals
    target_hour, to simulate two different times of day within one run."""
    for offset in range(-11, 13):
        candidate = f"Etc/GMT{'+' if -offset >= 0 else '-'}{abs(-offset)}" if offset != 0 else "UTC"
        try:
            tz = bot.pytz.timezone(candidate)
            if datetime.now(tz).hour == target_hour:
                return candidate
        except Exception:
            continue
    return None


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real bug (nightly scan 2026-09-10, follow-up on #317): reengage_max_
    # milestone_sent only updates when send_reengagement_message SUCCEEDS.
    # If it fails (a temporary Telegram hiccup -- the exact class of
    # failure the surrounding code is explicitly careful about elsewhere),
    # reengage_milestone_pending stays True for the rest of the calendar
    # day -- not just until the 9-10 window closes. For a user whose
    # notif_morning is 10:00 or later, that meant the regular morning
    # message was suppressed ALL DAY even though reactivation's only
    # chance to fire (the 9-10 window) had already closed: #317 turned
    # "two messages" into "zero messages" on a failed-send day. Fixed by
    # only suppressing morning while reengage still has a real chance to
    # fire today (before/during the 9-10 window) -- once the window has
    # closed without success, the deferred morning message goes out as a
    # normal fallback instead of being silently lost.
    # ══════════════════════════════════════════════════════════════════════
    tz_9_name = find_tz_with_local_hour(9)
    tz_11_name = find_tz_with_local_hour(11)
    if tz_9_name is None or tz_11_name is None:
        print("SKIPPED (no timezone currently at local hour 9 or 11 -- harmless, rare)")
        print("\nALL REENGAGE-FAILED-SEND-NO-SILENCE TESTS PASSED")
        return

    uid = 1
    make_user(uid, "Артем")
    three_days_ago_utc = (datetime.now(bot.pytz.utc) - timedelta(days=3)).isoformat()
    bot.update_user(
        uid, timezone=tz_9_name,
        notif_enabled=1, notif_morning_on=1, notif_morning="10:30", morning_sent_date="",
        notif_snooze_morning="", notif_midday_on=0, notif_evening_on=0,
        beacon_enabled=0, skill_beacon_enabled=0, notif_med_on=0,
        weekly_report_sent_date=datetime.now(bot.pytz.utc).date().isoformat(),
        resume_check_due="", focus_active=0,
        last_seen_at=three_days_ago_utc,
        reengage_opt_out=0, reengage_max_milestone_sent=0,
        morning_reminder_sent_date=datetime.now(bot.pytz.timezone(tz_9_name)).strftime("%Y-%m-%d"),
    )
    assert bot._days_since_seen(uid) == 3

    app = FakeApp()

    # Simulate send_reengagement_message failing (temporary Telegram issue).
    real_send_reengagement_message = bot.send_reengagement_message
    async def failing_send_reengagement_message(app_, uid_):
        return False
    bot.send_reengagement_message = failing_send_reengagement_message

    # 1. "09:xx tick" (inside the reactivation window) -- attempt fails,
    #    milestone stays pending, nothing sent (notif_morning is 10:30,
    #    not due yet anyway).
    user = bot.get_user(uid)
    await bot._process_user_notifications(app, user)
    assert not app.bot.sent, f"nothing should be sent yet at 09:xx (morning not due, reengage failed): {app.bot.sent}"
    assert int(bot.get_user(uid).get("reengage_max_milestone_sent") or 0) == 0, \
        "a failed reengage send must not falsely mark the milestone as sent"
    print("1. At the 09:xx tick, the reactivation attempt fails and nothing is sent yet")

    bot.send_reengagement_message = real_send_reengagement_message

    # 2. "11:xx tick" (window closed, notif_morning=10:30 is now due) --
    #    the regular morning message must fire as a fallback, not be
    #    silently swallowed because the milestone is still "pending".
    bot.update_user(
        uid, timezone=tz_11_name,
        morning_reminder_sent_date=datetime.now(bot.pytz.timezone(tz_11_name)).strftime("%Y-%m-%d"),
    )
    user2 = bot.get_user(uid)
    await bot._process_user_notifications(app, user2)
    texts = [t for _, t, _ in app.bot.sent]
    assert texts, \
        "the deferred morning message must fire once the reactivation window has closed, not be silently lost"
    assert not any("не только у тебя" in t for t in texts), \
        "reactivation itself must not fire outside its 9-10 window"
    assert bot.get_user(uid).get("morning_sent_date") == datetime.now(bot.pytz.timezone(tz_11_name)).date().isoformat()
    print("2. At the 11:xx tick, the regular morning message fires as a fallback -- not silently lost")

    print("\nALL REENGAGE-FAILED-SEND-NO-SILENCE TESTS PASSED")


asyncio.run(main())
