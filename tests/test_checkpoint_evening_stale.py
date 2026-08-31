import os, sys, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkpoint_evening_stale.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import pytz
import bot
bot.init_db()

# Avoid evening_day()'s 00:00-04:00 shift-to-yesterday window, same as the
# adjacent finish_evening fix's test -- otherwise "today" here and "today"
# inside the function under test land on different dates.
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


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone=SAFE_TZ)
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Same bug class as finish_evening (already fixed): the "Что получилось?"
    # step snapshots tasks_done ONCE into ctx.user_data["e_tasks_done"]. If
    # the evening ritual is abandoned (never finished) and the day rolls
    # over, checkpoint_evening_progress saves whatever was captured -- but
    # if the user marked something ELSE done via 📋 Задачи after that
    # snapshot and before abandoning the ritual, checkpoint_evening_progress
    # must not silently drop it from the saved evening record.
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    ctx.user_data["e_tasks_done"] = ["focus"]  # stale snapshot from ask_tasks_done
    bot.mark_tasks_done(uid, ["focus", "b1"], today)  # b1 marked later via 📋 Задачи

    bot.checkpoint_evening_progress(ctx, uid, today)
    saved = bot.get_diary(uid, "evening", today)
    assert set(saved.get("e_tasks_done", [])) == {"focus", "b1"}, \
        f"checkpoint_evening_progress must not lose a task marked done via 📋 Задачи, got {saved.get('e_tasks_done')}"
    print("1. checkpoint_evening_progress preserves a task marked done via 📋 Задачи after the stale snapshot")

    # The live "tasks_done" store itself must stay untouched by this
    # function (per its own documented contract -- it only checkpoints the
    # "evening" block, not the shared live store).
    live = bot.get_diary(uid, "tasks_done", today).get("done", [])
    assert set(live) == {"focus", "b1"}, live
    print("2. The shared live 'tasks_done' store is untouched, as documented")

    print("\nALL CHECKPOINT-EVENING-STALE TESTS PASSED")


main()
