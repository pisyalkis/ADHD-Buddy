import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_grant_command_reports_errors.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeBot:
    async def send_message(self, chat_id, text, **kw):
        pass


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("parse_mode")))


class FakeCtx:
    def __init__(self, args):
        self.args = args
        self.bot = FakeBot()


class FakeUpdate:
    def __init__(self, uid, msg):
        self.effective_user = FakeUser(uid)
        self.message = msg


async def main():
    admin_uid = 999  # matches NOTIFY_USER_ID
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (999, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(admin_uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real complaint: "/grant 115561526 30" produced NO reaction whatsoever.
    # grant_command was the only /admin-style command without a top-level
    # try/except -- and the global error handler (on_error) only prints to
    # server logs, never replies. Any exception inside the grant flow was
    # therefore completely invisible in the chat. Simulate that by making
    # grant_access_days blow up, and confirm the command now reports it
    # instead of going silent.
    # ══════════════════════════════════════════════════════════════════════
    original = bot.grant_access_days
    def boom(uid, days):
        raise RuntimeError("simulated failure")
    bot.grant_access_days = boom
    try:
        msg = FakeMsg()
        ctx = FakeCtx(["115561526", "30"])
        await bot.grant_command(FakeUpdate(admin_uid, msg), ctx)
        assert len(msg.sent) == 1, msg.sent
        assert "Ошибка" in msg.sent[0][0] and "simulated failure" in msg.sent[0][0], msg.sent
        print("1. grant_command now reports an exception instead of silently doing nothing")
    finally:
        bot.grant_access_days = original

    # Sanity: the normal, successful path still works and replies as before.
    msg2 = FakeMsg()
    ctx2 = FakeCtx(["115561526", "30"])
    await bot.grant_command(FakeUpdate(admin_uid, msg2), ctx2)
    assert len(msg2.sent) == 1, msg2.sent
    assert "+30 дн." in msg2.sent[0][0], msg2.sent
    print("2. The normal successful /grant flow is unaffected")

    print("\nALL GRANT-COMMAND-REPORTS-ERRORS TESTS PASSED")


asyncio.run(main())
