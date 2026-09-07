import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coworking_notif_unify.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 900
        self.texts = []

    async def edit_text(self, text, **kw):
        self.texts.append((text, kw.get("reply_markup")))
        return self

    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        self.texts.append((text, kw.get("reply_markup")))
        return m


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
        self.answers = []

    async def answer(self, text=None, **kw):
        self.answers.append(text)


class FakeUpdate:
    def __init__(self, uid, data=None, message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message)
        self.message = None


class FakeBot:
    def __init__(self):
        self.sent = []
        self.deleted = []
        self._next_id = 1000

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        self._next_id += 1
        class M:
            pass
        m = M()
        m.message_id = self._next_id
        return m

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class FakeCtx:
    def __init__(self, bot_):
        self.user_data = {}
        self.bot = bot_


class FakeApp:
    def __init__(self, bot_):
        self.bot = bot_


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def create_session(creator_uid, minutes_from_now=30, duration=45):
    start = (datetime.now(bot.pytz.utc) + timedelta(minutes=minutes_from_now)).isoformat()
    end = (datetime.now(bot.pytz.utc) + timedelta(minutes=minutes_from_now + duration)).isoformat()
    conn = sqlite3.connect(bot.DB_PATH)
    cur = conn.execute(
        "INSERT INTO coworking_sessions(creator_id, start_at, end_at, duration_minutes, started_notified, finished_notified) "
        "VALUES (?, ?, ?, ?, 0, 0)",
        (creator_uid, start, end, duration)
    )
    session_id = cur.lastrowid
    conn.commit(); conn.close()
    bot.join_coworking_session(session_id, creator_uid)
    return session_id


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real bug (IDEAS.md 2026-09-06): coworking_join_callback/
    # coworking_leave_callback push their "who's in" screen through
    # send_tracked_notification on channel coworking_{id} -- self-cleans,
    # replaces on repeat. check_coworking_sessions' start/end pushes used
    # plain app.bot.send_message instead: untracked, no self-cleanup, and
    # crucially did NOT replace the still-open "who's in / 🚪 Не смогу"
    # screen from before the session started -- both messages sat in the
    # chat side by side, the old one with a now-meaningless leave button.
    # ══════════════════════════════════════════════════════════════════════
    uid1 = 1
    make_user(uid1, "Артем")
    uid2 = 2
    make_user(uid2, "Вика")
    fake_bot = FakeBot()
    session_id = create_session(uid1, minutes_from_now=30, duration=45)

    # A join happens first -- this leaves a tracked coworking_{id} message
    # (the "who's in" screen) open for both participants, via the
    # already-existing send_tracked_notification path.
    upd_join = FakeUpdate(uid2, data=f"coworking_join_{session_id}", message=FakeMsg(uid2))
    await bot.coworking_join_callback(upd_join, FakeCtx(fake_bot))
    assert len(fake_bot.sent) == 2, fake_bot.sent
    open_mid_before_1 = bot._get_notif_msg_id(uid1, f"coworking_{session_id}")
    open_mid_before_2 = bot._get_notif_msg_id(uid2, f"coworking_{session_id}")
    assert open_mid_before_1 is not None and open_mid_before_2 is not None
    print("1. Joining leaves a tracked 'who's in' screen open for both participants (setup)")

    # 2. The session becomes due -- force it into the past so
    #    check_coworking_sessions picks it up as a start.
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("UPDATE coworking_sessions SET start_at=? WHERE id=?",
                 ((datetime.now(bot.pytz.utc) - timedelta(minutes=1)).isoformat(), session_id))
    conn.commit(); conn.close()
    fake_app = FakeApp(fake_bot)
    fake_bot.sent.clear()
    await bot.check_coworking_sessions(fake_app)
    # The bug fix: the OLD "who's in" message for each participant must have
    # been deleted (send_tracked_notification's replace-on-same-channel),
    # not left dangling alongside a brand new untracked one.
    assert (uid1, open_mid_before_1) in fake_bot.deleted, \
        f"the pre-start 'who's in' screen must be replaced, not left stale: {fake_bot.deleted}"
    assert (uid2, open_mid_before_2) in fake_bot.deleted, fake_bot.deleted
    assert len(fake_bot.sent) == 2, f"exactly one 'started' push per participant: {fake_bot.sent}"
    assert all("началась" in t for _, t, _ in fake_bot.sent), fake_bot.sent
    # And the channel now tracks the NEW "started" message, not the old one.
    new_mid_1 = bot._get_notif_msg_id(uid1, f"coworking_{session_id}")
    assert new_mid_1 is not None and new_mid_1 != open_mid_before_1
    print("2. Session start replaces the stale 'who's in' screen with the 'started' notification (bug fix)")

    # 3. The session becomes due to finish -- same channel again, must
    #    replace the "started" message with "finished", not stack up.
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("UPDATE coworking_sessions SET end_at=? WHERE id=?",
                 ((datetime.now(bot.pytz.utc) - timedelta(minutes=1)).isoformat(), session_id))
    conn.commit(); conn.close()
    fake_bot.sent.clear()
    fake_bot.deleted.clear()
    await bot.check_coworking_sessions(fake_app)
    assert (uid1, new_mid_1) in fake_bot.deleted, \
        f"the 'started' message must be replaced by 'finished', not left stale: {fake_bot.deleted}"
    assert len(fake_bot.sent) == 2, fake_bot.sent
    assert all("Готово" in t for _, t, _ in fake_bot.sent), fake_bot.sent
    print("3. Session finish replaces the 'started' notification with 'finished' on the same channel")

    print("\nALL COWORKING-NOTIF-UNIFY TESTS PASSED")


asyncio.run(main())
