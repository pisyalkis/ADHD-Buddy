import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_buddy_ping_clears_flags.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
    async def edit_text(self, text, **kw): return self
    async def reply_text(self, text, **kw): return self


class FakeQuery:
    def __init__(self, uid):
        self.from_user = FakeUser(uid); self.message = FakeMsg(uid); self.data = "buddy_ping"
    async def answer(self): pass
    async def edit_message_text(self, *a, **kw): return self.message


class FakeUpdate:
    def __init__(self, uid):
        self.callback_query = FakeQuery(uid)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug: buddy_ping never called clear_awaiting_flags, unlike essentially
    # every other screen-rendering callback handler in the file (81 other
    # call sites). A stale awaiting_* flag left over from an earlier,
    # abandoned action (e.g. the user opened "Обратная связь", got
    # distracted, then tapped an old "💬 Написать бадди сейчас" button
    # sitting in their chat history) stayed active -- so the user's next
    # ordinary text message would be silently swallowed into the stale
    # handler (e.g. saved as feedback) instead of being treated normally,
    # the same bug class clear_awaiting_flags's own docstring documents.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender, buddy_name) VALUES (1, 'Артем', 'M', 'Вика')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    ctx = FakeCtx()
    ctx.user_data["awaiting_feedback"] = True  # stale flag from an earlier, abandoned action

    upd = FakeUpdate(uid)
    await bot.buddy_ping(upd, ctx)

    assert ctx.user_data.get("awaiting_feedback") is False, \
        f"buddy_ping must clear stale awaiting_* flags like every other screen handler, got: {ctx.user_data}"
    print("1. buddy_ping clears a stale awaiting_feedback flag, like buddy_menu/buddy_set already do")

    print("\nALL BUDDY-PING-CLEARS-FLAGS TESTS PASSED")


asyncio.run(main())
