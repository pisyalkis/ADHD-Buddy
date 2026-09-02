import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_grammar_and_empty_input.db")
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
        self.message_id = 1
        self.text = ""
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeUpdate:
    def __init__(self, uid, text):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.message = FakeMsg(uid)
        self.message.text = text
        self.callback_query = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = None


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug 1: "Утро записано/записана" was gendered on the USER's gender
    # instead of the neuter noun "Утро" -- female users saw a grammar error.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Вика', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    user = bot.get_user(uid)
    pinned_text = bot._build_pinned_tasks_text(user, [], "")
    assert "Утро записано" in pinned_text, pinned_text
    assert "записана" not in pinned_text, pinned_text
    print("1. _build_pinned_tasks_text always says 'Утро записано' (invariant), regardless of gender")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 2: personalize() dict keys are lowercase, str.replace is
    # case-sensitive -- a capitalized placeholder (button/sentence start)
    # never got replaced.
    # ══════════════════════════════════════════════════════════════════════
    result_m = bot.personalize("😵 Отвлёкся(ась)", "M")
    result_f = bot.personalize("😵 Отвлёкся(ась)", "F")
    assert result_m == "😵 Отвлёкся", result_m
    assert result_f == "😵 Отвлеклась", result_f
    print("2. personalize() correctly replaces a capitalized irregular placeholder")

    # Lowercase usage must still work exactly as before.
    assert bot.personalize("ты отвлёкся(ась) снова", "F") == "ты отвлеклась снова"
    print("3. personalize() still works for lowercase placeholders (no regression)")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 3: got_name (onboarding) only rejected names > 30 chars, not an
    # empty string after strip() -- unlike the Settings rename screen.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    ctx2 = FakeCtx()
    upd2 = FakeUpdate(uid2, "   ")
    state = await bot.got_name(upd2, ctx2)
    assert state == bot.ONBOARD_NAME, state
    assert "пустым" in upd2.message.sent[0][0], upd2.message.sent
    u2 = bot.get_user(uid2)
    assert u2.get("name", "") == "", "empty name must NOT be saved"
    print("4. got_name rejects an empty/whitespace-only name and asks again")

    # A real name must still work as before.
    upd2b = FakeUpdate(uid2, "Настя")
    ctx2b = FakeCtx()
    state2 = await bot.got_name(upd2b, ctx2b)
    assert state2 == bot.ONBOARD_GENDER, state2
    assert bot.get_user(uid2).get("name") == "Настя"
    print("5. got_name still accepts a real name as before")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 4: handle_text's awaiting_buddy branch didn't check for an empty
    # string after strip(), unlike the neighboring awaiting_name branch.
    # ══════════════════════════════════════════════════════════════════════
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Настя', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone="Asia/Tbilisi")
    ctx3 = FakeCtx()
    ctx3.user_data["awaiting_buddy"] = True
    upd3 = FakeUpdate(uid3, "   ")
    await bot.handle_text(upd3, ctx3)
    assert ctx3.user_data.get("awaiting_buddy") is True, \
        "empty buddy name must NOT clear awaiting_buddy -- must ask again"
    u3 = bot.get_user(uid3)
    assert not u3.get("buddy_name"), f"empty buddy name must not be saved, got: {u3.get('buddy_name')!r}"
    assert upd3.message.sent, "must reply asking to try again"
    assert "пустым" in upd3.message.sent[0][0], upd3.message.sent
    print("6. handle_text/awaiting_buddy rejects an empty/whitespace-only name and asks again")

    # A real buddy name must still work as before.
    ctx3b = FakeCtx()
    ctx3b.user_data["awaiting_buddy"] = True
    upd3b = FakeUpdate(uid3, "Олег")
    await bot.handle_text(upd3b, ctx3b)
    assert ctx3b.user_data.get("awaiting_buddy") is False
    assert bot.get_user(uid3).get("buddy_name") == "Олег"
    print("7. handle_text/awaiting_buddy still accepts a real name as before")

    print("\nALL GRAMMAR-AND-EMPTY-INPUT TESTS PASSED")


asyncio.run(main())
