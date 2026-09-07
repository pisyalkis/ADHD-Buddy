import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coworking_cleanup.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


def make_user(uid, name, tz_name="Asia/Tbilisi"):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone=tz_name)


def create_finished_session(creator_uid, end_days_ago, extra_participant=None):
    """A session that finished `end_days_ago` days ago (both start_at and
    end_at safely in the past)."""
    start = (datetime.now(bot.pytz.utc) - timedelta(days=end_days_ago, hours=1)).isoformat()
    end = (datetime.now(bot.pytz.utc) - timedelta(days=end_days_ago)).isoformat()
    conn = sqlite3.connect(bot.DB_PATH)
    cur = conn.execute(
        "INSERT INTO coworking_sessions(creator_id, start_at, end_at, duration_minutes, started_notified, finished_notified) "
        "VALUES (?, ?, ?, 30, 1, 1)",
        (creator_uid, start, end)
    )
    session_id = cur.lastrowid
    conn.commit(); conn.close()
    bot.join_coworking_session(session_id, creator_uid)
    if extra_participant is not None:
        bot.join_coworking_session(session_id, extra_participant)
    return session_id


class FakeApp:
    pass


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-09-06 -- "архивация/очистка таблиц
    # коворкинга"): coworking_sessions/coworking_participants grow forever,
    # nothing ever deletes a finished session's row. The screens only ever
    # query OPEN sessions (start_at > now), so old rows are pure unbounded
    # growth with zero product value.
    #
    # The tricky part: get_coworking_alumni (PR "оповещать о новой сессии
    # тех, кто уже участвовал") used to read straight from
    # coworking_participants -- naively cleaning old sessions would have
    # silently un-enrolled long-time participants from future "new
    # session" notifications. Fixed by moving alumni status to its own
    # users.coworking_ever_joined flag, decoupled from session history.
    # ══════════════════════════════════════════════════════════════════════
    old_creator = 1
    make_user(old_creator, "Артем")
    old_participant = 2
    make_user(old_participant, "Вика")
    old_session = create_finished_session(old_creator, end_days_ago=90, extra_participant=old_participant)

    recent_creator = 3
    make_user(recent_creator, "Игорь")
    recent_session = create_finished_session(recent_creator, end_days_ago=10)

    # 1. join_coworking_session/create_coworking_session set the new alumni
    #    flag on the user row.
    assert bot.get_user(old_creator).get("coworking_ever_joined") == "1"
    assert bot.get_user(old_participant).get("coworking_ever_joined") == "1"
    assert bot.get_user(recent_creator).get("coworking_ever_joined") == "1"
    print("1. Creating/joining a session sets users.coworking_ever_joined")

    # 2. Before cleanup, both sessions and all their participant rows exist.
    conn = sqlite3.connect(bot.DB_PATH)
    sessions_before = conn.execute("SELECT COUNT(*) FROM coworking_sessions").fetchone()[0]
    participants_before = conn.execute("SELECT COUNT(*) FROM coworking_participants").fetchone()[0]
    conn.close()
    assert sessions_before == 2 and participants_before == 3, (sessions_before, participants_before)
    print("2. Both the old (90d) and recent (10d) sessions exist before cleanup (setup)")

    # 3. cleanup_old_coworking_sessions (retention 60 days) deletes the OLD
    #    session and its participant rows, but leaves the recent one intact.
    await bot.cleanup_old_coworking_sessions(FakeApp())
    conn = sqlite3.connect(bot.DB_PATH)
    remaining_sessions = {r[0] for r in conn.execute("SELECT id FROM coworking_sessions").fetchall()}
    remaining_participant_sessions = {r[0] for r in conn.execute("SELECT session_id FROM coworking_participants").fetchall()}
    conn.close()
    assert old_session not in remaining_sessions, remaining_sessions
    assert recent_session in remaining_sessions, remaining_sessions
    assert old_session not in remaining_participant_sessions, remaining_participant_sessions
    print("3. cleanup_old_coworking_sessions deletes the old (>60d) session and its participants, keeps the recent one")

    # 4. THE CRITICAL PART: even though the old session's participant rows
    #    are gone, both the old creator and the old participant are STILL
    #    counted as coworking alumni (their history was purged, but their
    #    "ever participated" status must survive it).
    alumni = set(bot.get_coworking_alumni())
    assert old_creator in alumni, \
        f"an old session's creator must still count as alumni after cleanup: {alumni}"
    assert old_participant in alumni, \
        f"an old session's participant must still count as alumni after cleanup: {alumni}"
    print("4. Alumni status survives the cleanup of the session history that earned it (the critical fix)")

    # 5. Someone who never participated is still correctly excluded.
    never_participated = 4
    make_user(never_participated, "Соня")
    alumni2 = set(bot.get_coworking_alumni())
    assert never_participated not in alumni2, alumni2
    print("5. Someone who never participated is still correctly excluded from alumni")

    # 6. exclude_uid still works as before.
    alumni3 = set(bot.get_coworking_alumni(exclude_uid=old_creator))
    assert old_creator not in alumni3 and old_participant in alumni3, alumni3
    print("6. get_coworking_alumni(exclude_uid=...) still excludes the given user")

    print("\nALL COWORKING-CLEANUP TESTS PASSED")


asyncio.run(main())
