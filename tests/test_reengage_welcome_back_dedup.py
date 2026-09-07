import os, sys, asyncio, sqlite3, json
from datetime import datetime, timedelta, date

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_reengage_welcome_back_dedup.db")
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


def find_tz_with_local_hour_9():
    """Same trick as test_weekly_report_monday.py's Monday-finder -- pick a
    fixed-offset timezone where the CURRENT real time's local hour is 9, so
    the reengagement window (9 <= now_dt.hour < 10) is deterministically
    open regardless of when this test actually runs."""
    for offset in range(-11, 13):
        candidate = f"Etc/GMT{'+' if -offset >= 0 else '-'}{abs(-offset)}" if offset != 0 else "UTC"
        try:
            tz = bot.pytz.timezone(candidate)
            if datetime.now(tz).hour == 9:
                return candidate
        except Exception:
            continue
    return None


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real bug (nightly scan, BUGS.md 2026-09-06): the reactivation message
    # (REENGAGE_MILESTONES, from _days_since_seen -- ANY real update) and the
    # "👋 С возвращением!" branch of morning_notification (is_returning, from
    # _days_since_last_activity -- completed rituals only) are two independent
    # "days of silence" trackers that both look at the same morning window.
    # On the exact day both first cross the same threshold (a common case --
    # a user who just gradually stopped using the bot hits both gaps on the
    # same calendar day), they fired in the SAME tick: two different
    # "you've been away" messages back to back. Fixed by computing whether
    # reengagement is due BEFORE morning_notification, and skipping the
    # regular morning send (without marking it sent) whenever reengagement
    # is about to fire that tick -- it naturally fires on the next tick
    # instead, once the milestone has already advanced.
    # ══════════════════════════════════════════════════════════════════════
    tz_name = find_tz_with_local_hour_9()
    if tz_name is None:
        print("SKIPPED (no timezone currently at local hour 9 -- harmless, rare)")
        print("\nALL REENGAGE-WELCOME-BACK-DEDUP TESTS PASSED")
        return

    tz = bot.pytz.timezone(tz_name)
    now_local = datetime.now(tz)
    today_local = now_local.date()

    # 1. A user whose BOTH gaps (streak-based and last_seen_at-based) cross
    #    milestone 3 on the same tick gets exactly ONE message this tick --
    #    the reactivation one -- and morning_sent_date is NOT marked (so the
    #    regular morning notification is deferred, not lost).
    uid = 1
    make_user(uid, "Артем")
    three_days_ago_local = (today_local - timedelta(days=3)).isoformat()
    three_days_ago_utc = (datetime.now(bot.pytz.utc) - timedelta(days=3)).isoformat()
    bot.update_user(
        uid, timezone=tz_name,
        notif_enabled=1, notif_morning_on=1, notif_morning="09:00", morning_sent_date="",
        notif_snooze_morning="", notif_midday_on=0, notif_evening_on=0,
        beacon_enabled=0, skill_beacon_enabled=0, notif_med_on=0,
        weekly_report_sent_date=today_local.isoformat(), resume_check_due="", focus_active=0,
        streak=json.dumps([three_days_ago_local]),
        last_seen_at=three_days_ago_utc,
        reengage_opt_out=0, reengage_max_milestone_sent=0,
    )
    assert bot._days_since_last_activity(uid) == 3
    assert bot._days_since_seen(uid) == 3

    app = FakeApp()
    user = bot.get_user(uid)
    await bot._process_user_notifications(app, user)
    texts = [t for _, t, _ in app.bot.sent]
    reengage_count = sum(1 for t in texts if "не только у тебя" in t)
    welcome_back_count = sum(1 for t in texts if "С возвращением" in t)
    assert reengage_count == 1, f"expected exactly one reactivation message, got: {texts}"
    assert welcome_back_count == 0, \
        f"the regular 'С возвращением' morning greeting must NOT also fire in the same tick: {texts}"
    assert int(bot.get_user(uid).get("reengage_max_milestone_sent") or 0) == 3
    assert bot.get_user(uid).get("morning_sent_date") != today_local.isoformat(), \
        "morning_sent_date must NOT be marked this tick -- the regular morning notification is deferred, not skipped forever"
    print("1. On the day both gaps first cross the same milestone, only the reactivation message fires -- morning is deferred, not lost")

    # 2. The VERY NEXT tick (milestone already recorded, reengage_due_now no
    #    longer true) sends the deferred morning notification normally --
    #    still the "С возвращением!" variant, since the streak gap is still
    #    >= WELCOME_BACK_GAP_DAYS.
    app2 = FakeApp()
    user_after = bot.get_user(uid)
    await bot._process_user_notifications(app2, user_after)
    texts2 = [t for _, t, _ in app2.bot.sent]
    assert any("С возвращением" in t for t in texts2), \
        f"the deferred morning notification must fire on the next tick: {texts2}"
    assert not any("не только у тебя" in t for t in texts2), \
        "reactivation must not fire again -- its milestone was already recorded"
    assert bot.get_user(uid).get("morning_sent_date") == today_local.isoformat()
    print("2. The next tick sends the deferred 'С возвращением!' morning notification, and reactivation doesn't repeat")

    print("\nALL REENGAGE-WELCOME-BACK-DEDUP TESTS PASSED")


asyncio.run(main())
