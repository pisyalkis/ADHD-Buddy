import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_resume_check_single_message.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [91000]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.edited = []

    async def reply_text(self, text, **kw):
        return FakeMsg(self.chat_id)

    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data, message):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message)
        self.message = None


class FakeBot:
    def __init__(self):
        self.sent = []
        self.deleted = []

    async def send_message(self, chat_id, text, **kw):
        m = FakeMsg(chat_id)
        self.sent.append((chat_id, text, m.message_id))
        return m

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class FakeCtx:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real gap (from the audit): send_resume_check ("⏰ Отдых закончен?",
    # fired ~15 min after "☕ Отдыхаю") was a raw bot.send_message, never
    # registered under any notif channel -- answering it via midday_callback
    # (it shares midday_kb) never deleted it, and it never self-deleted.
    # ══════════════════════════════════════════════════════════════════════
    fbot = FakeBot()
    ok = await bot.send_resume_check(fbot, uid)
    assert ok is True
    resume_mid = bot._get_notif_msg_id(uid, "resume_check")
    assert resume_mid is not None, "send_resume_check must now be tracked under its own channel"
    print("1. send_resume_check is tracked under channel 'resume_check'")

    conn = sqlite3.connect(bot.DB_PATH)
    row = conn.execute(
        "SELECT delete_at FROM scheduled_deletions WHERE chat_id=? AND message_id=?", (uid, resume_mid)
    ).fetchone()
    conn.close()
    assert row is not None, "the resume-check message must be scheduled for self-deletion"
    print("2. It's scheduled to self-delete after the standard silence TTL")

    # Answering it via midday_callback (shares midday_kb) must edit it in
    # place into the response, not delete it and send a new one.
    resume_screen = FakeMsg(chat_id=uid); resume_screen.message_id = resume_mid
    ctx = FakeCtx(fbot)
    upd = FakeUpdate(uid, "mid_ok", resume_screen)
    await bot.midday_callback(upd, ctx)
    assert (uid, resume_mid) not in fbot.deleted, \
        "answering the resume-check (mid_ok) must edit it in place, not delete it"
    assert resume_screen.edited, "the resume-check message must be edited into the response"
    assert bot._get_notif_msg_id(uid, "resume_check") is None
    print("3. Answering the resume-check via midday_callback edits it in place and clears tracking")

    print("\nALL RESUME-CHECK-SINGLE-MESSAGE TESTS PASSED")


asyncio.run(main())
