import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_evening_stale_tasksdone.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import pytz
import bot
bot.init_db()

# Pick a timezone where it's currently NOT in evening_day()'s 00:00-04:00
# shift-to-yesterday window -- otherwise finish_evening's "today" (evening_day)
# and this test's calendar-date "today" (used for mark_tasks_done) land on
# different dates, and the test exercises nothing real. Same trick already
# used elsewhere in this test suite for Sunday-dependent tests.
SAFE_TZ = "Asia/Tbilisi"
for offset in range(-11, 13):
    candidate = f"Etc/GMT{'+' if -offset >= 0 else '-'}{abs(-offset)}" if offset != 0 else "UTC"
    try:
        cand = pytz.timezone(candidate)
        if datetime.now(cand).hour >= 5:
            SAFE_TZ = candidate
            break
    except Exception:
        continue


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
    bot.update_user(uid, timezone=SAFE_TZ)
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    bot.save_diary(uid, "morning", {
        "focus": "Сходить к врачу", "b1": "Купить хлеб", "b2": "Позвонить маме",
    }, for_date=today)

    # ══════════════════════════════════════════════════════════════════════
    # Bug (Artem): marked tasks done throughout the day via 📋 Задачи, but
    # the evening report showed the wrong done/not-done state. Root cause:
    # the evening ritual's E_TASKS_DONE step snapshots ctx.user_data once at
    # ask_tasks_done, and it is NOT in RESUME_FIELDS_EVENING -- if the ritual
    # is interrupted AFTER that step and resumed later, the snapshot goes
    # stale relative to anything marked via 📋 Задачи in the meantime, and
    # finish_evening used to blindly overwrite "tasks_done" with it.
    # ══════════════════════════════════════════════════════════════════════

    # 1. Evening ritual starts: tasks-done step snapshots current state
    bot.mark_tasks_done(uid, ["focus"], today)  # marked via 📋 Задачи before evening starts
    ctx = FakeCtx()
    await bot.ask_tasks_done(FakeMsg(), uid, ctx, today)
    assert set(ctx.user_data["e_tasks_done"]) == {"focus"}, ctx.user_data
    print("1. ask_tasks_done seeds e_tasks_done from the live DB state")

    # 2. Ritual gets interrupted (imagine user closes the app); later, DURING
    #    the interruption, the user marks another task done via 📋 Задачи --
    #    this updates the DB but NOT the already-seeded ctx.user_data.
    bot.mark_tasks_done(uid, ["b1"], today)
    live_done = bot.get_diary(uid, "tasks_done", today).get("done", [])
    assert set(live_done) == {"focus", "b1"}, live_done
    assert set(ctx.user_data["e_tasks_done"]) == {"focus"}, "sanity: the in-memory snapshot must still be stale here"
    print("2. Marking b1 done via 📋 Задачи during the interruption updates the DB, not the stale snapshot")

    # 3. User resumes and finishes the evening ritual -- finish_evening must
    #    NOT silently drop the b1 mark made in the meantime.
    ctx.user_data.update({
        "e_ach": "", "e_praise": "", "e_highlights": "",
        "e_selfcare": [], "e_energy": 3,
        "e_a": "", "e_b1": "", "e_b2": "", "e_c1": "", "e_c2": "", "e_c3": "",
    })
    await bot.finish_evening(FakeMsg(), uid, ctx)

    final_done = set(bot.get_diary(uid, "tasks_done", today).get("done", []))
    assert final_done == {"focus", "b1"}, \
        f"finish_evening must not lose a task marked done via 📋 Задачи during an interruption, got {final_done}"
    print("3. finish_evening preserves the b1 mark made via 📋 Задачи after the stale snapshot was taken")

    print("\nALL EVENING-STALE-TASKSDONE TESTS PASSED")


asyncio.run(main())
