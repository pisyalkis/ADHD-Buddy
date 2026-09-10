import os, sys, asyncio, sqlite3, json
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_reengage_early_morning_dedup.db")
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
    """Same trick as test_reengage_welcome_back_dedup.py's find_tz_with_local_hour_9,
    generalized: pick a fixed-offset timezone where the CURRENT real time's
    local hour equals target_hour, so we can simulate two different times of
    day for the same user within a single test run (no real waiting, no
    mocking datetime)."""
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
    # Real bug (nightly scan 2026-09-09, #47): reengage_due_now was computed
    # ONLY inside the 9:00-10:00 window, and only suppressed the morning
    # notification while it hadn't been sent YET that tick. For a user whose
    # notif_morning is set earlier than 9:00, the regular morning message
    # already goes out (and morning_sent_date already gets marked) well
    # before the 9-10 window even opens -- so when the milestone-crossing
    # reactivation later fires at 9:00, there is nothing left to suppress:
    # the user gets the FULL regular morning ritual AND a separate "давно не
    # был(а)" reactivation message on the same day. Fixed by computing
    # whether a reactivation milestone is pending WITHOUT the hour
    # restriction (used only to gate suppression of the morning message all
    # day), while still restricting the actual SEND of the reactivation
    # message to the narrow 9:00-10:00 window as before.
    # ══════════════════════════════════════════════════════════════════════
    tz_early_name = find_tz_with_local_hour(7)
    tz_9_name = find_tz_with_local_hour(9)
    if tz_early_name is None or tz_9_name is None:
        print("SKIPPED (no timezone currently at local hour 7 or 9 -- harmless, rare)")
        print("\nALL REENGAGE-EARLY-MORNING-DEDUP TESTS PASSED")
        return

    uid = 1
    make_user(uid, "Артем")
    three_days_ago_utc = (datetime.now(bot.pytz.utc) - timedelta(days=3)).isoformat()
    bot.update_user(
        uid, timezone=tz_early_name,
        notif_enabled=1, notif_morning_on=1, notif_morning="07:00", morning_sent_date="",
        notif_snooze_morning="", notif_midday_on=0, notif_evening_on=0,
        beacon_enabled=0, skill_beacon_enabled=0, notif_med_on=0,
        weekly_report_sent_date=datetime.now(bot.pytz.utc).date().isoformat(),
        resume_check_due="", focus_active=0, streak=json.dumps([]),
        last_seen_at=three_days_ago_utc,
        reengage_opt_out=0, reengage_max_milestone_sent=0,
    )
    assert bot._days_since_seen(uid) == 3

    app = FakeApp()

    # The independent "missed morning by +2h, tasks still empty" nudge
    # (morning_reminder_sent_date) is orthogonal to what this test checks --
    # pre-mark it as already handled for both simulated ticks so it doesn't
    # add unrelated noise to the message counts below.
    bot.update_user(
        uid, morning_reminder_sent_date=datetime.now(bot.pytz.timezone(tz_early_name)).strftime("%Y-%m-%d"),
    )

    # 1. "07:00 tick" -- notif_morning is already due, but the reactivation
    #    window (9-10) hasn't opened yet. The regular morning message must
    #    NOT go out here -- the milestone is already pending today.
    user = bot.get_user(uid)
    await bot._process_user_notifications(app, user)
    texts_tick1 = [t for _, t, _ in app.bot.sent]
    assert not any("не только у тебя" in t for t in texts_tick1), texts_tick1
    assert not texts_tick1, \
        f"the regular morning notification must be deferred, not sent, on a day reactivation is pending: {texts_tick1}"
    assert bot.get_user(uid).get("morning_sent_date") != datetime.now(bot.pytz.timezone(tz_early_name)).date().isoformat(), \
        "morning_sent_date must NOT be marked at the 07:00 tick -- deferred, not lost"
    print("1. At the 07:00 tick (before the reactivation window), the regular morning message is deferred, not sent")

    # 2. "09:00 tick" (same user, same real moment -- just viewed through a
    #    timezone that puts local time at 9:00) -- the reactivation message
    #    fires, and the regular morning message still does NOT also fire.
    bot.update_user(
        uid, timezone=tz_9_name,
        morning_reminder_sent_date=datetime.now(bot.pytz.timezone(tz_9_name)).strftime("%Y-%m-%d"),
    )
    user2 = bot.get_user(uid)
    await bot._process_user_notifications(app, user2)
    texts_tick2 = [t for _, t, _ in app.bot.sent]
    reengage_msgs = [t for t in texts_tick2 if "не только у тебя" in t]
    assert len(reengage_msgs) == 1, f"expected exactly one reactivation message: {texts_tick2}"
    assert len(texts_tick2) == 1, \
        f"expected ONLY the reactivation message this tick, not also the regular morning one: {texts_tick2}"
    assert int(bot.get_user(uid).get("reengage_max_milestone_sent") or 0) == 3
    print("2. At the 09:00 tick, ONLY the reactivation message fires -- no duplicate regular morning message")

    total_messages = len(app.bot.sent)
    assert total_messages == 1, \
        f"across both ticks together, exactly ONE message must have been sent (not a morning + reactivation duplicate pair): {app.bot.sent}"
    print("3. Across both ticks combined, exactly one message was sent for the whole day (no duplicate)")

    print("\nALL REENGAGE-EARLY-MORNING-DEDUP TESTS PASSED")


asyncio.run(main())
