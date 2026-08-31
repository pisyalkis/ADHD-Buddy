import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_evening_midnight_tasksdone.db")
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

    # Find a timezone where it's currently between 00:00 and 04:00 local time
    # -- the exact window evening_day() treats as "still yesterday evening",
    # so finishing the evening ritual there is the scenario Artem hit.
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
    assert ev_day != real_today, "sanity check: evening_day must resolve to yesterday in this window"

    # ══════════════════════════════════════════════════════════════════════
    # Set up: user did their morning ritual "yesterday" (which is what
    # evening_day resolves "today" to at this hour), then reviews the
    # evening past midnight.
    # ══════════════════════════════════════════════════════════════════════
    bot.save_diary(uid, "morning", {"focus": "Сходить к врачу", "b1": "Купить хлеб"}, for_date=ev_day)

    ctx = FakeCtx()
    ctx.user_data["e_a"] = ""
    ctx.user_data["e_tasks_done"] = ["focus"]  # marked the A-task done in tonight's checklist
    msg = FakeMsg()
    await bot.finish_evening(msg, uid, ctx)

    # ── Bug 1 (Artem: "отчёт по задачам пропал из вечернего отчёта") ───────
    closing_text = msg.sent[-1]
    assert "📋 *Задачи дня:*" in closing_text, \
        f"the day's task summary must still appear in the closing message, got: {closing_text!r}"
    assert "Сходить к врачу" in closing_text
    print("1. The '📋 Задачи дня:' section still appears in the closing message when finishing past midnight")

    # ── tasks_done was written under evening_day's date (yesterday), not the
    #    brand new calendar day ──────────────────────────────────────────────
    yesterday_done = bot.get_diary(uid, "tasks_done", ev_day).get("done", [])
    assert "focus" in yesterday_done, yesterday_done
    print("2. tasks_done is correctly attributed to the day the evening ritual reviewed (evening_day), not to 'now'")

    # ── Bug 2 (Artem: "галочки подтягиваются с предыдущего дня") ────────────
    # Opening the FRESH new day's task menu must NOT show yesterday's marks.
    todays_done = bot.get_diary(uid, "tasks_done", real_today).get("done", [])
    assert todays_done == [], \
        f"a brand new calendar day must start with an empty tasks_done, got {todays_done}"
    print("3. The new calendar day's own tasks_done is untouched -- no leaked checkmarks from last night's review")

    print("\nALL EVENING-MIDNIGHT-TASKSDONE TESTS PASSED")


asyncio.run(main())
