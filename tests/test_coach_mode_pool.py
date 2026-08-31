import os, sys, asyncio, sqlite3, types

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coach_mode_pool.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = "fake-key-for-tests"

_fake_reply = {"text": ""}

class FakeContent:
    def __init__(self, text): self.text = text

class FakeResp:
    def __init__(self, text): self.content = [FakeContent(text)]

class FakeMessages:
    def create(self, **kw):
        return FakeResp(_fake_reply["text"])

class FakeAnthropic:
    def __init__(self, api_key=None):
        self.messages = FakeMessages()

fake_module = types.ModuleType("anthropic")
fake_module.Anthropic = FakeAnthropic
sys.modules["anthropic"] = fake_module

def set_fake_reply(text):
    _fake_reply["text"] = text

import bot
bot.init_db()


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, text=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})
        self.callback_query = None
        self.message = FakeMsg()
        self.message.text = text


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = None


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # Same bug class: coach_mode stuck on must not swallow "add to pool" either.
    ctx = FakeCtx()
    ctx.user_data["coach_mode"] = True
    set_fake_reply('{"intent": "add_pool", "items": ["купить хлеб"]}')
    upd = FakeUpdate(uid, text="добавь в список дел купить хлеб")
    await bot.handle_text(upd, ctx)

    pool = bot.get_pool_tasks(uid)
    assert len(pool) == 1 and pool[0]["text"] == "купить хлеб", \
        f"add_pool must work even while coach_mode is stuck on, got {pool}"
    print("1. 'Добавь в список дел' works even while coach_mode is stuck on")

    print("\nALL COACH-MODE-POOL TESTS PASSED")


asyncio.run(main())
