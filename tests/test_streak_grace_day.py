import os, sys, sqlite3, json
from datetime import timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_streak_grace_day.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def days_ago(base, n):
    return (base - timedelta(days=n)).isoformat()


def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-28): calc_streak used to zero out on
    # ANY single missed evening, even though the bot explicitly fights
    # all-or-nothing shame thinking (unfinished_shame) everywhere else.
    # calc_streak itself didn't follow that principle. One isolated missed
    # day should now be forgiven ("freeze"), like Duolingo -- but only ONE
    # per computed chain, and never at the "today not done yet" boundary.
    # ══════════════════════════════════════════════════════════════════════
    today = bot.evening_day(TBILISI)

    # 1. One isolated missed day (yesterday gap) in an otherwise unbroken
    #    chain is forgiven -- streak keeps counting through it.
    uid1 = 1
    make_user(uid1, "Артем")
    # today, (missing: 1 day ago), 2,3,4 days ago all present
    dates = [days_ago(today, 0), days_ago(today, 2), days_ago(today, 3), days_ago(today, 4)]
    bot.update_user(uid1, streak=json.dumps(dates))
    streak1 = bot.calc_streak(uid1)
    assert streak1 == 4, f"one isolated missed day must be forgiven, expected streak 4, got {streak1}"
    print("1. A single isolated missed day is forgiven -- the streak still counts through it (4)")

    # 2. TWO missed days in the same chain -- only the first gap is
    #    forgiven, the streak stops at the second gap (no infinite skip-a-
    #    day gaming).
    uid2 = 2
    make_user(uid2, "Вика")
    # today, (missing 1), 2 present, (missing 3), 4 present
    dates2 = [days_ago(today, 0), days_ago(today, 2), days_ago(today, 4)]
    bot.update_user(uid2, streak=json.dumps(dates2))
    streak2 = bot.calc_streak(uid2)
    assert streak2 == 2, f"a second gap must NOT be forgiven, expected streak 2 (stops at the 2nd gap), got {streak2}"
    print("2. A second missed day in the same chain is NOT forgiven -- the count stops there (2)")

    # 3. Regression: no gaps at all -- unchanged behavior, matches the old
    #    algorithm exactly.
    uid3 = 3
    make_user(uid3, "Игорь")
    dates3 = [days_ago(today, 0), days_ago(today, 1), days_ago(today, 2)]
    bot.update_user(uid3, streak=json.dumps(dates3))
    streak3 = bot.calc_streak(uid3)
    assert streak3 == 3, f"an unbroken chain must count normally, got {streak3}"
    print("3. An unbroken chain (no gaps) still counts normally (3) -- no regression")

    # 4. Sanity preserved from the existing timezone test: if TODAY itself
    #    is missing, the count is still 0 (not "grace-forgiven") -- "today
    #    not done yet" is normal, not a freeze-worthy gap, and must not
    #    silently borrow credit from yesterday's chain.
    uid4 = 4
    make_user(uid4, "Соня")
    dates4 = [days_ago(today, 1), days_ago(today, 2)]
    bot.update_user(uid4, streak=json.dumps(dates4))
    streak4 = bot.calc_streak(uid4)
    assert streak4 == 0, f"with today's entry missing, streak must still report 0, got {streak4}"
    print("4. With today's own entry missing, calc_streak still reports 0 (unchanged) -- grace never applies at position 0")

    print("\nALL STREAK-GRACE-DAY TESTS PASSED")


main()
