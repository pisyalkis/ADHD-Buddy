import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_got_energy_ask_plan_a.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.callback_query = FakeQuery(uid, data)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1

    # ══════════════════════════════════════════════════════════════════════
    # Regression from PR #122 (found by the 9th checkup round): ask_plan_a
    # gained a required uid param (to build pool suggestions), the
    # RESUME_FIELDS_EVENING lambda got updated, but this direct call site
    # inside got_energy was missed -- a TypeError on the single most common
    # evening-flow transition (energy level -> task A), hitting EVERY user
    # who reaches the end of the evening ritual.
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    upd = FakeUpdate(uid, data="energy_3")
    next_state = await bot.got_energy(upd, ctx)  # must not raise TypeError
    assert next_state == bot.E_A
    assert ctx.user_data["e_energy"] == 3
    text = upd.callback_query.message.last_text
    assert "задача A" in text, text
    print("1. got_energy correctly advances to the task-A prompt without crashing")

    print("\nALL GOT-ENERGY-ASK-PLAN-A TESTS PASSED")


asyncio.run(main())
