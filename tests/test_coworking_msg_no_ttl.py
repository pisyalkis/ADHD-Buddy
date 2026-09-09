import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coworking_msg_no_ttl.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


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
        self._next_id = 1000

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        self._next_id += 1
        class M:
            pass
        m = M(); m.message_id = self._next_id
        return m

    async def delete_message(self, chat_id, message_id):
        pass


class FakeCtx:
    def __init__(self, bot_):
        self.user_data = {}
        self.bot = bot_


def make_user(uid, name, tz_name="Asia/Tbilisi"):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone=tz_name)


def scheduled_deletion_count():
    conn = sqlite3.connect(bot.DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM scheduled_deletions").fetchone()[0]
    conn.close()
    return n


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real bug (nightly scan 2026-09-08): the coworking session screen (the
    # only place with "🚪 Не смогу") went through send_tracked_notification
    # WITHOUT ttl_seconds, defaulting to INACTIVE_SCREEN_TTL_SEC (15 min).
    # Since sessions can now be scheduled hours or a day ahead ("завтра
    # 09:00", #300), the message -- and with it the only leave button --
    # silently vanishes long before the session even starts, with no way
    # to get it back (go_coworking just offers "Присоединиться" again for
    # an already-joined session).
    # ══════════════════════════════════════════════════════════════════════
    creator = 1
    make_user(creator, "Артем")
    alumnus = 2
    make_user(alumnus, "Вика")

    # Give the alumnus coworking history so _notify_coworking_alumni
    # actually reaches them.
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("UPDATE users SET coworking_ever_joined='1' WHERE user_id=?", (alumnus,))
    conn.commit(); conn.close()

    # 1. Creating a session (coworking_set_duration): neither the creator's
    #    own confirmation NOR the alumni notification schedules a self-
    #    deletion.
    fake_bot = FakeBot()
    ctx = FakeCtx(fake_bot)
    ctx.user_data["coworking_pending_start_utc"] = (datetime.now(bot.pytz.utc) + timedelta(hours=20)).isoformat()
    upd = FakeUpdate(creator, data="coworking_dur_25", message=FakeMsg(creator))
    await bot.coworking_set_duration(upd, ctx)
    assert len(fake_bot.sent) == 2, fake_bot.sent  # creator confirm + alumnus notify
    assert scheduled_deletion_count() == 0, \
        "neither the creator confirmation nor the alumni notify may self-delete (bug fix)"
    print("1. Creating a session: neither the creator's screen nor the alumni notify schedules self-deletion")

    # Find the session id from the DB to drive join/leave.
    sessions = bot.get_open_coworking_sessions()
    session_id = sessions[0]["id"]

    # 2. Someone else joining (coworking_join_callback): the broadcast to
    #    all participants (including the creator) doesn't self-delete either.
    joiner = 3
    make_user(joiner, "Игорь")
    fake_bot2 = FakeBot()
    ctx2 = FakeCtx(fake_bot2)
    upd2 = FakeUpdate(joiner, data=f"coworking_join_{session_id}", message=FakeMsg(joiner))
    await bot.coworking_join_callback(upd2, ctx2)
    assert scheduled_deletion_count() == 0, "the join broadcast must not self-delete (bug fix)"
    print("2. Joining a session: the participant-count broadcast doesn't schedule self-deletion")

    # 3. Someone leaving (coworking_leave_callback): the broadcast to the
    #    remaining participants doesn't self-delete either.
    fake_bot3 = FakeBot()
    ctx3 = FakeCtx(fake_bot3)
    upd3 = FakeUpdate(joiner, data=f"coworking_leave_{session_id}", message=FakeMsg(joiner))
    await bot.coworking_leave_callback(upd3, ctx3)
    assert scheduled_deletion_count() == 0, "the leave broadcast must not self-delete (bug fix)"
    print("3. Leaving a session: the updated-count broadcast doesn't schedule self-deletion")

    print("\nALL COWORKING-MSG-NO-TTL TESTS PASSED")


asyncio.run(main())
