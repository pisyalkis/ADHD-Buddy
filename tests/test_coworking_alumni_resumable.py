import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coworking_alumni_resumable.db")
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
            message_id = 901
        return M()


class FakeApp:
    def __init__(self, bot_):
        self.bot = bot_


def make_user(uid, name, tz_name="Asia/Tbilisi"):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone=tz_name)


def create_past_session_with_participant(uid):
    start = (datetime.now(bot.pytz.utc) - timedelta(hours=5)).isoformat()
    end = (datetime.now(bot.pytz.utc) - timedelta(hours=4)).isoformat()
    conn = sqlite3.connect(bot.DB_PATH)
    cur = conn.execute(
        "INSERT INTO coworking_sessions(creator_id, start_at, end_at, duration_minutes, started_notified, finished_notified) "
        "VALUES (?, ?, ?, 30, 1, 1)",
        (uid, start, end)
    )
    session_id = cur.lastrowid
    conn.commit(); conn.close()
    bot.join_coworking_session(session_id, uid)


def pending_queue_uids(session_id):
    conn = sqlite3.connect(bot.DB_PATH)
    rows = conn.execute(
        "SELECT user_id FROM coworking_alumni_notify_queue WHERE session_id=?", (session_id,)
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real bug (nightly scan 2026-09-09): _notify_coworking_alumni sent to
    # every alumnus synchronously, in one loop, inside one call -- with no
    # persisted record of who'd already been reached. A process restart
    # mid-loop (a crash, a deploy) silently stranded everyone the loop
    # hadn't gotten to yet, forever -- nothing would ever retry them. Fixed
    # via a persistent coworking_alumni_notify_queue: the intended recipient
    # list is written BEFORE any send is attempted, each row is cleared only
    # after an actual attempt (success or failure), and the per-minute
    # check_coworking_sessions job flushes any leftover rows -- simulating a
    # crash here means creating an alumnus, manually inserting queue rows
    # (as the crashed call would have left them, having queued but never
    # attempted), and confirming a later, independent call finishes the job.
    # ══════════════════════════════════════════════════════════════════════
    creator = 1
    make_user(creator, "Артем")
    alumnus_a = 2; alumnus_b = 3
    make_user(alumnus_a, "Вика"); make_user(alumnus_b, "Игорь")
    create_past_session_with_participant(alumnus_a)
    create_past_session_with_participant(alumnus_b)

    # A future session, as if just created by the creator -- but simulate
    # the crash: the queue was written (the durable "intent") but the
    # process died before a single send was attempted, so both alumni are
    # still sitting in the queue table with nothing in fake_bot.sent.
    start_utc = (datetime.now(bot.pytz.utc) + timedelta(hours=3)).isoformat()
    conn = sqlite3.connect(bot.DB_PATH)
    cur = conn.execute(
        "INSERT INTO coworking_sessions(creator_id, start_at, end_at, duration_minutes, created_at) "
        "VALUES (?, ?, ?, 30, ?)",
        (creator, start_utc, (datetime.fromisoformat(start_utc) + timedelta(minutes=30)).isoformat(),
         datetime.now(bot.pytz.utc).isoformat())
    )
    session_id = cur.lastrowid
    conn.execute("INSERT INTO coworking_participants(session_id, user_id, joined_at) VALUES (?, ?, ?)",
                 (session_id, creator, datetime.now(bot.pytz.utc).isoformat()))
    conn.commit(); conn.close()
    bot._queue_coworking_alumni_notify(session_id, [alumnus_a, alumnus_b])

    # 1. Sanity: the crash left both alumni pending, nobody notified yet.
    assert pending_queue_uids(session_id) == {alumnus_a, alumnus_b}
    print("1. Simulated crash: both alumni are queued but nobody has been notified yet")

    # 2. A LATER, independent call -- exactly what check_coworking_sessions
    #    does every minute -- picks up the leftover queue and finishes the
    #    job, with no new coworking_set_duration call at all.
    fake_bot = FakeBot()
    await bot._flush_coworking_alumni_queue(fake_bot, session_id)
    targets = {c for c, _, _ in fake_bot.sent}
    assert targets == {alumnus_a, alumnus_b}, \
        f"a later flush must reach every alumnus stranded by the simulated crash: {fake_bot.sent}"
    assert pending_queue_uids(session_id) == set(), \
        f"the queue must be empty once everyone has been attempted: {pending_queue_uids(session_id)}"
    print("2. An independent later flush (as check_coworking_sessions runs every minute) reaches every stranded alumnus")

    # 3. check_coworking_sessions itself -- not just the helper directly --
    #    also drains any leftover queue, end-to-end.
    bot._queue_coworking_alumni_notify(session_id, [alumnus_a, alumnus_b])
    fake_bot2 = FakeBot()
    app2 = FakeApp(fake_bot2)
    await bot.check_coworking_sessions(app2)
    targets2 = {c for c, _, _ in fake_bot2.sent}
    assert targets2 == {alumnus_a, alumnus_b}, \
        f"check_coworking_sessions itself must drain the leftover queue: {fake_bot2.sent}"
    print("3. check_coworking_sessions (the real per-minute job) drains any leftover queue end-to-end")

    # 4. A session whose start time has ALREADY PASSED by the time we flush
    #    (long outage) is not sent to at all -- joining would be rejected
    #    anyway -- just cleared, no dead invites.
    past_session_start = (datetime.now(bot.pytz.utc) - timedelta(minutes=5)).isoformat()
    conn = sqlite3.connect(bot.DB_PATH)
    cur = conn.execute(
        "INSERT INTO coworking_sessions(creator_id, start_at, end_at, duration_minutes, created_at) "
        "VALUES (?, ?, ?, 30, ?)",
        (creator, past_session_start, (datetime.fromisoformat(past_session_start) + timedelta(minutes=30)).isoformat(),
         datetime.now(bot.pytz.utc).isoformat())
    )
    past_session_id = cur.lastrowid
    conn.commit(); conn.close()
    bot._queue_coworking_alumni_notify(past_session_id, [alumnus_a])
    fake_bot3 = FakeBot()
    await bot._flush_coworking_alumni_queue(fake_bot3, past_session_id)
    assert not fake_bot3.sent, \
        f"a session whose start already passed during the outage must not send dead invites: {fake_bot3.sent}"
    assert pending_queue_uids(past_session_id) == set()
    print("4. A session whose start time already passed during the outage is cleared without sending dead invites")

    print("\nALL COWORKING-ALUMNI-RESUMABLE TESTS PASSED")


asyncio.run(main())
