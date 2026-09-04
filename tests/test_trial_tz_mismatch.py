import os, sys, sqlite3
import datetime as _dt_module

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_trial_tz_mismatch.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()
import pytz

# ══════════════════════════════════════════════════════════════════════
# Bug: created_at is always stamped in the bot's default USER_TIMEZONE
# (Asia/Tbilisi), because at first /start the real user timezone isn't
# known yet (set later in onboarding, see get_user()'s own comment).
# But get_access_status/get_trial_days_left compared that created_at
# against "today" computed in the user's REAL (possibly very different)
# timezone -- for a user far enough from Tbilisi, the two calendars
# disagree on "today" for part of every day, so the trial doesn't last
# exactly TRIAL_DAYS calendar days.
#
# Freeze "now" to a fixed UTC instant where Tbilisi (UTC+4) has already
# rolled over to 2026-09-04 while Los Angeles (UTC-7, PDT) is still on
# 2026-09-03 -- deterministic regardless of when this test actually runs.
# ══════════════════════════════════════════════════════════════════════
FIXED_UTC = _dt_module.datetime(2026, 9, 4, 2, 0, 0, tzinfo=_dt_module.timezone.utc)


class FrozenDateTime(_dt_module.datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FIXED_UTC.replace(tzinfo=None)
        return FIXED_UTC.astimezone(tz)


def main():
    tbilisi = pytz.timezone("Asia/Tbilisi")
    la = pytz.timezone("America/Los_Angeles")
    assert FIXED_UTC.astimezone(tbilisi).date().isoformat() == "2026-09-04"
    assert FIXED_UTC.astimezone(la).date().isoformat() == "2026-09-03"

    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    # created_at is always stamped in Tbilisi's calendar (see get_user()) --
    # at this frozen instant that's 2026-09-04, i.e. "registered right now".
    bot.update_user(uid, timezone="America/Los_Angeles", created_at="2026-09-04")
    user = bot.get_user(uid)

    bot.datetime = FrozenDateTime
    try:
        days_left = bot.get_trial_days_left(user)
        status = bot.get_access_status(user)
    finally:
        bot.datetime = _dt_module.datetime

    # Registered "just now" (by the same clock created_at was stamped
    # with) must leave exactly TRIAL_DAYS days, regardless of the user's
    # own configured timezone -- both sides of the comparison must use
    # the same reference timezone.
    assert days_left == bot.TRIAL_DAYS, \
        f"trial days-left must be measured in the same timezone created_at was stamped in, got {days_left} (expected {bot.TRIAL_DAYS})"
    assert status == "trial", f"user must still be within trial right after registration, got {status}"
    print(f"1. get_trial_days_left/get_access_status agree with created_at's own timezone reference ({days_left} days left, status={status})")

    print("\nALL TRIAL-TZ-MISMATCH TESTS PASSED")


main()
