import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_morning_streak_evening_day.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import pytz
import bot
bot.init_db()


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append(text)
        return self


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1

    # Need a timezone currently in evening_day()'s 00:00-04:00 shift window
    # -- the exact window where completing the morning ritual used to zero
    # out the streak until 4 AM.
    midnight_tz = None
    for offset in range(-11, 13):
        candidate = f"Etc/GMT{'+' if -offset >= 0 else '-'}{abs(-offset)}" if offset != 0 else "UTC"
        try:
            cand = pytz.timezone(candidate)
            if datetime.now(cand).hour < 4:
                midnight_tz = candidate
                break
        except Exception:
            continue

    if not midnight_tz:
        print("SKIPPED (no timezone currently in the 00:00-04:00 window -- harmless, rare)")
        return

    bot.update_user(uid, timezone=midnight_tz)
    tz = bot.get_user_tz(bot.get_user(uid))
    now = datetime.now(tz)
    real_today = now.date().isoformat()
    ev_day = bot.evening_day(tz).isoformat()
    assert ev_day != real_today, "sanity: evening_day must resolve to yesterday in this window"

    # Streak already has entries for the two days BEFORE today (evening_day)
    # -- today itself not yet recorded, since the user hasn't finished this
    # morning's ritual yet.
    day_minus_1 = (bot.date.fromisoformat(ev_day) - timedelta(days=1)).isoformat()
    day_minus_2 = (bot.date.fromisoformat(ev_day) - timedelta(days=2)).isoformat()
    bot.update_user(uid, streak=bot.json.dumps([day_minus_2, day_minus_1]))
    streak_before = bot.calc_streak(uid)
    assert streak_before == 0, \
        f"sanity: with today's entry missing, calc_streak breaks on the gap and reports 0, got {streak_before}"

    # ══════════════════════════════════════════════════════════════════════
    # Bug: completing the morning ritual just after midnight used to record
    # the streak under the brand-new calendar date instead of evening_day's
    # date, making calc_streak() (which reads by evening_day) see the
    # newest entry as "one day ahead" and report 0 instead of the real
    # continued streak.
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    msg = FakeMsg()
    await bot.finish_morning(msg, uid, ctx)

    streak_after = bot.calc_streak(uid)
    assert streak_after == 3, \
        f"completing the morning ritual just after midnight must extend the streak to 3, got {streak_after}"
    print("1. Streak correctly extends to 3 right after finishing the morning ritual just after midnight")

    saved_streak = bot.json.loads(bot.get_user(uid)["streak"])
    assert ev_day in saved_streak and real_today not in saved_streak, \
        f"the new entry must be stored under evening_day's date, not the brand-new calendar date, got {saved_streak}"
    print("2. The new streak entry is stored under evening_day's date, matching what calc_streak reads")

    print("\nALL MORNING-STREAK-EVENING-DAY TESTS PASSED")


asyncio.run(main())
