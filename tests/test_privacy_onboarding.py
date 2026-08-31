import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_privacy_onboarding.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    async def delete_message(self, chat_id, message_id):
        pass


class FakeMsg:
    def __init__(self):
        self.sent = []
        self.chat_id = 1
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid):
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid):
        self.callback_query = FakeQuery(uid)
        self.effective_user = FakeUser(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeBot()


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1

    ctx = FakeCtx()
    upd = FakeUpdate(uid)
    # No struggles selected -> generic branch of step 2.
    await bot.send_explain_step(upd, ctx, step=2, then="cta")
    text = upd.callback_query.message.last_text
    assert "🔒" in text and "Приватность" in text, text
    assert "О боте" in text, "must point to where the full explanation lives"
    print("1. Onboarding step 2 (generic branch) ends with a brief privacy mention pointing to «О боте → Приватность»")

    # With struggles selected -> the "lines" branch of step 2.
    ctx2 = FakeCtx()
    ctx2.user_data["onboard_problems"] = ["overload"]
    upd2 = FakeUpdate(uid)
    await bot.send_explain_step(upd2, ctx2, step=2, then="cta")
    text2 = upd2.callback_query.message.last_text
    assert "🔒" in text2 and "Приватность" in text2, text2
    print("2. Onboarding step 2 (struggles-tailored branch) also ends with the same privacy mention")

    print("\nALL PRIVACY-ONBOARDING TESTS PASSED")


asyncio.run(main())
