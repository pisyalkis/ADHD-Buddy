import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_today_context_backfill.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug: get_today_context (used by send_coach, beacon_technique_done,
    # send_task_beacon, send_work_start_reminder, go_focus,
    # focus_start_callback, buddy_ping, send_resume_check,
    # midday_notification, midday_callback -- 10 call sites) never called
    # apply_yesterday_plan_if_empty, unlike morning_start/📋 Задачи (which
    # call it directly). So a user with an empty today but a real plan from
    # last night's "Планы на завтра" would see "задачи не заданы" on these
    # 10 screens, but a filled-in plan on morning_start/📋 Задачи -- an
    # inconsistency depending only on which screen they happened to open.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    user = bot.get_user(uid)
    tz = bot.get_user_tz(user)
    today_date = datetime.now(tz).date()
    yesterday_iso = (today_date - timedelta(days=1)).isoformat()

    # Yesterday evening: a real plan for tomorrow ("Планы на завтра").
    bot.save_diary(uid, "evening", {
        "e_a": "Сдать отчёт", "e_b1": "Позвонить маме", "e_b2": "",
        "e_c1": "", "e_c2": "", "e_c3": "", "e_energy": 3,
    }, for_date=yesterday_iso)

    # Today's morning diary is untouched -- nothing filled yet.
    today_iso, morning, done_set = bot.get_today_context(user)
    assert morning.get("focus") == "Сдать отчёт", \
        f"get_today_context must backfill yesterday's plan into today's empty morning, got: {morning}"
    assert morning.get("b1") == "Позвонить маме", morning
    print("1. get_today_context backfills yesterday's evening plan when today is empty")

    # It must also have actually persisted the backfill (same DB-write side
    # effect as the direct apply_yesterday_plan_if_empty call sites), so a
    # second, independent read of today's morning diary sees it too.
    persisted = bot.get_diary(uid, "morning", today_iso)
    assert persisted.get("focus") == "Сдать отчёт", \
        f"the backfilled plan must be saved to today's diary, not just returned in-memory, got: {persisted}"
    print("2. The backfill is persisted to today's morning diary (survives a fresh read)")

    # ══════════════════════════════════════════════════════════════════════
    # Sanity: a user who already set a real task today keeps it -- the
    # backfill must never clobber a deliberately-set task.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Вика', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    user2 = bot.get_user(uid2)
    today_iso2, _, _ = bot.get_today_context(user2)
    bot.save_diary(uid2, "evening", {"e_a": "Чужая задача"}, for_date=(today_date - timedelta(days=1)).isoformat())
    bot.save_diary(uid2, "morning", {"focus": "Своя задача, уже поставлена"}, for_date=today_iso2)
    _, morning2, _ = bot.get_today_context(user2)
    assert morning2.get("focus") == "Своя задача, уже поставлена", \
        f"an already-set task for today must never be overwritten by the backfill, got: {morning2}"
    print("3. A task already set for today is never overwritten by the backfill")

    print("\nALL TODAY-CONTEXT-BACKFILL TESTS PASSED")


main()
