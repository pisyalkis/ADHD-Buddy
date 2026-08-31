import os, sys, asyncio, sqlite3, types

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coach_no_operation_roleplay.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = "fake-key-for-tests"

_captured = {"system": None, "messages": None}

class FakeContent:
    def __init__(self, text): self.text = text

class FakeResp:
    def __init__(self, text): self.content = [FakeContent(text)]

class FakeMessages:
    def create(self, **kw):
        _captured["system"] = kw.get("system")
        _captured["messages"] = kw.get("messages")
        return FakeResp("Начни с одного маленького шага.")

class FakeAnthropic:
    def __init__(self, api_key=None):
        self.messages = FakeMessages()

fake_module = types.ModuleType("anthropic")
fake_module.Anthropic = FakeAnthropic
sys.modules["anthropic"] = fake_module

import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
        self.text = None
    async def reply_text(self, text, **kw):
        return self
    async def edit_text(self, text, **kw):
        self.text = text
        return self


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real incident: sending the coach a message like "grant 115561526 30"
    # got back a fabricated JSON blob ("operation": "grant", "success":
    # true, "new_balance": 30) -- the bot has NO token/balance system at
    # all; the model simply role-played a fake successful admin operation
    # because nothing in the system prompt told it not to. The system
    # prompt must now explicitly forbid pretending to execute operations
    # or fabricating JSON/success confirmations.
    # ══════════════════════════════════════════════════════════════════════
    msg = FakeMsg(chat_id=uid)
    await bot.send_coach(msg, "grant 115561526 30", uid, ctx=None)

    system_prompt = _captured["system"]
    assert system_prompt is not None, "the coach must actually call the model"
    for phrase in ("нет доступа", "базе данных", "не притворяйся", "поддельный результат"):
        assert phrase in system_prompt, \
            f"expected guardrail phrase {phrase!r} missing from coach system prompt: {system_prompt}"
    print("1. The coach's system prompt explicitly forbids role-playing backend operations or fabricating results")

    # The user's raw text still reaches the model unmodified (the guardrail
    # lives in the system prompt, not by filtering/blocking user input).
    assert _captured["messages"][-1]["content"] == "grant 115561526 30"
    print("2. The suspicious text is still passed through as-is -- the fix is instructional, not a content filter")

    print("\nALL COACH-NO-OPERATION-ROLEPLAY TESTS PASSED")


asyncio.run(main())
