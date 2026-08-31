import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_buddy_promo_single_message.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [111000]
    def __init__(self, chat_id, text=None):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.text = text
        self.edited = []
        self.reply_calls = []

    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
        return self

    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        self.reply_calls.append((text, kw.get("reply_markup")))
        return m


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=None, message=None, text_message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message) if data is not None else None
        self.message = text_message


class FakeBot:
    def __init__(self, tracked_msg):
        self.tracked_msg = tracked_msg

    async def edit_message_text(self, chat_id, message_id, text, **kw):
        if message_id == self.tracked_msg.message_id:
            await self.tracked_msg.edit_text(text, **kw)
        else:
            raise Exception("unknown message_id")


class FakeCtx:
    def __init__(self, bot=None):
        self.user_data = {}
        self.bot = bot


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()

    # ══════════════════════════════════════════════════════════════════════
    # 👥 Бадди: menu -> "Добавить бадди" prompt -> typed name -> confirmation
    # must all land on the SAME message (track_key="buddy").
    # ══════════════════════════════════════════════════════════════════════
    menu_screen = FakeMsg(chat_id=uid)
    ctx = FakeCtx(FakeBot(menu_screen))
    upd = FakeUpdate(uid, data="go_buddy", message=menu_screen)
    await bot.buddy_menu(upd, ctx)
    assert ctx.user_data.get("buddy_msg_id") == menu_screen.message_id
    assert menu_screen.edited and "Бадди" in menu_screen.edited[-1][0]
    print("1. buddy_menu tracks itself under track_key='buddy'")

    upd2 = FakeUpdate(uid, data="buddy_set", message=menu_screen)
    await bot.buddy_set(upd2, ctx)
    assert menu_screen.edited[-1][0] == "Напиши имя своего бадди:", menu_screen.edited[-1]
    assert not menu_screen.reply_calls, "buddy_set must edit in place, not send a new message"
    print("2. buddy_set edits the SAME tracked message into the name prompt")

    user_text = FakeMsg(chat_id=uid, text="Маша")
    upd3 = FakeUpdate(uid, text_message=user_text)
    await bot.handle_text(upd3, ctx)
    assert not user_text.reply_calls, \
        "typing the buddy name must not spawn a new message from the user's own message"
    assert "Бадди добавлен" in menu_screen.edited[-1][0], menu_screen.edited[-1]
    print("3. Typing the buddy name edits the SAME tracked message with the confirmation")

    # ══════════════════════════════════════════════════════════════════════
    # 🎁 Промокод: go_promo prompt -> typed code -> confirmation, same message.
    # ══════════════════════════════════════════════════════════════════════
    promo_screen = FakeMsg(chat_id=uid)
    ctx2 = FakeCtx(FakeBot(promo_screen))
    upd4 = FakeUpdate(uid, data="go_promo", message=promo_screen)
    await bot.go_promo(upd4, ctx2)
    assert ctx2.user_data.get("promo_msg_id") == promo_screen.message_id
    assert promo_screen.edited and "Промокод" in promo_screen.edited[-1][0]
    print("4. go_promo tracks itself under track_key='promo'")

    user_code = FakeMsg(chat_id=uid, text="NOSUCHCODE")
    upd5 = FakeUpdate(uid, text_message=user_code)
    await bot.handle_text(upd5, ctx2)
    assert not user_code.reply_calls, \
        "typing the promo code must not spawn a new message from the user's own message"
    assert promo_screen.edited[-1][0], promo_screen.edited
    print("5. Typing the promo code edits the SAME tracked message with the result")

    print("\nALL BUDDY-PROMO-SINGLE-MESSAGE TESTS PASSED")


asyncio.run(main())
