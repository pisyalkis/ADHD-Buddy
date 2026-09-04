import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_menu_command.db")
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
        self.from_user = FakeUser(chat_id)
    async def edit_text(self, text, **kw):
        raise Exception("can't edit a user's own message")
    async def reply_text(self, text, **kw):
        self.sent = (text, kw.get("reply_markup"))
        return self


class FakeUpdate:
    def __init__(self, uid, msg):
        self.message = msg
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)
        self.callback_query = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Follow-up request (Victoria): the native Telegram "Menu" button can
    # only insert a slash command into the compose box, not open our inline
    # keyboard screen directly. /menu is the direct answer -- it must
    # render the actual main menu (same as tapping "☰ Меню" / go_menu),
    # just reachable via a text command instead of a callback_query.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    msg = FakeMsg(uid)
    upd = FakeUpdate(uid, msg)
    ctx = FakeCtx()
    await bot.menu_command(upd, ctx)

    assert hasattr(msg, "sent"), "menu_command must actually send a reply"
    text, kb = msg.sent
    assert "Главное меню" in text, f"menu_command must show the main menu screen, got text: {text!r}"
    flat = buttons_of(kb)
    assert flat, "menu_command's reply must carry the real main menu keyboard, not an empty one"
    print("1. /menu renders the same main menu screen as tapping ☰ Меню")

    print("\nALL MENU-COMMAND TESTS PASSED")


asyncio.run(main())
