import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coworking_join_fixes.db")
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

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class M:
            message_id = 901
        return M()


class FakeCtx:
    def __init__(self, bot_):
        self.user_data = {}
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
    # Real bugs (nightly scan, BUGS.md 2026-09-06), both in coworking_join_callback:
    # (a) the return value of join_coworking_session (True=new join,
    #     False=already joined) was never checked -- a repeat/double tap of
    #     "Присоединиться" (typical ADHD behavior the rest of the file
    #     specifically avoids provoking) broadcast an updated-count push to
    #     every participant even though the count hadn't changed;
    #     (b) unlike similar callbacks on background/persistent messages
    #     (buddy_ping), it never called clear_awaiting_and_cancel_ritual --
    #     an open awaiting_*-flag on another screen wasn't cleared.
    # ══════════════════════════════════════════════════════════════════════
    uid1 = 1
    make_user(uid1, "Артем")
    uid2 = 2
    make_user(uid2, "Вика")
    session_id = create_session(uid1)

    # 1. First join: broadcasts the updated count to all participants
    #    (creator + new joiner), as before -- no regression.
    fake_bot = FakeBot()
    join_msg = FakeMsg(uid2)
    upd_join = FakeUpdate(uid2, data=f"coworking_join_{session_id}", message=join_msg)
    await bot.coworking_join_callback(upd_join, FakeCtx(fake_bot))
    assert set(bot.get_coworking_participants(session_id)) == {uid1, uid2}
    assert len(fake_bot.sent) == 2, f"a genuinely new join must broadcast to all {2} participants: {fake_bot.sent}"
    assert upd_join.callback_query.answers[0] == "Готово, ты в сессии!"
    print("1. A real new join broadcasts the updated count to all participants, as before")

    # 2. Repeat join (double tap, same user, same session): must NOT
    #    broadcast anything -- the count hasn't changed. This is the bug fix.
    fake_bot2 = FakeBot()
    upd_join_again = FakeUpdate(uid2, data=f"coworking_join_{session_id}", message=FakeMsg(uid2))
    await bot.coworking_join_callback(upd_join_again, FakeCtx(fake_bot2))
    assert not fake_bot2.sent, \
        f"a repeat join by the same user must NOT re-broadcast the (unchanged) participant count: {fake_bot2.sent}"
    assert upd_join_again.callback_query.answers[0] == "Ты уже в этой сессии.", \
        upd_join_again.callback_query.answers
    print("2. A repeat join by the same user does not re-broadcast the unchanged count (bug fix)")

    # 3. coworking_join_callback clears an open awaiting_*-flag from another
    #    screen -- e.g. mid-edit of the display name. This is the second
    #    bug fix.
    ctx3 = FakeCtx(FakeBot())
    ctx3.user_data["awaiting_name"] = True
    uid3 = 3
    make_user(uid3, "Игорь")
    upd_join3 = FakeUpdate(uid3, data=f"coworking_join_{session_id}", message=FakeMsg(uid3))
    await bot.coworking_join_callback(upd_join3, ctx3)
    assert not ctx3.user_data.get("awaiting_name"), \
        "coworking_join_callback must clear an open awaiting_*-flag from another screen (bug fix)"
    print("3. coworking_join_callback clears an open awaiting_*-flag from another screen (bug fix)")

    print("\nALL COWORKING-JOIN-FIXES TESTS PASSED")


asyncio.run(main())
