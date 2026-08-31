import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_ritual_first_step_edits_menu.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self):
        self.edited = []
        self.sent = []
        self.edit_should_fail = False
    async def edit_text(self, text, **kw):
        if self.edit_should_fail:
            raise Exception("message is not modified")
        self.edited.append((text, kw.get("reply_markup")))
        return self
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def reply_animation(self, **kw):
        class _A:
            animation = None
        return _A()


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data)
        self.message = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real request: tapping 🌙 Вечер (or ☀️ Утро) from the main menu should
    # replace the menu message in place, not send a brand new one -- same
    # principle as every other section fixed this session. Before this fix,
    # the very FIRST ritual step always sent a new message via reply_text
    # regardless of whether the calling screen could be edited.
    # ══════════════════════════════════════════════════════════════════════
    upd_evening = FakeUpdate(uid, data="go_evening")
    ctx_evening = FakeCtx()
    await bot.evening_start(upd_evening, ctx_evening)
    menu_msg = upd_evening.callback_query.message
    assert menu_msg.edited and not menu_msg.sent, \
        f"evening_start's first message must edit the menu screen in place, got edited={menu_msg.edited} sent={menu_msg.sent}"
    print("1. Tapping 🌙 Вечер from the menu edits the menu message in place")

    # Falls back to a new message if the menu screen can no longer be edited.
    upd_evening2 = FakeUpdate(uid, data="go_evening")
    upd_evening2.callback_query.message.edit_should_fail = True
    ctx_evening2 = FakeCtx()
    await bot.evening_start(upd_evening2, ctx_evening2)
    assert upd_evening2.callback_query.message.sent, \
        "must fall back to a new message when the menu screen can't be edited"
    print("2. Falls back to a new message when editing the menu screen fails")

    # Same fix for ☀️ Утро (same underlying helper, _render_step_msg).
    upd_morning = FakeUpdate(uid, data="go_morning")
    ctx_morning = FakeCtx()
    await bot.morning_start(upd_morning, ctx_morning)
    menu_msg2 = upd_morning.callback_query.message
    assert menu_msg2.edited and not menu_msg2.sent, \
        f"morning_start's first message must also edit the menu screen in place, got edited={menu_msg2.edited} sent={menu_msg2.sent}"
    print("3. Tapping ☀️ Утро from the menu also edits the menu message in place (same underlying fix)")

    print("\nALL RITUAL-FIRST-STEP-EDITS-MENU TESTS PASSED")


asyncio.run(main())
