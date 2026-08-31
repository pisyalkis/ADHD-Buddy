import os, sys, asyncio, sqlite3, types

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_dead_end_menu_buttons.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = "fake-key-for-test"

# Fake anthropic module so send_coach's exception path is reachable without
# a real network call -- messages.create simply raises.
fake_anthropic = types.ModuleType("anthropic")
class FakeMessages:
    def create(self, **kw):
        raise Exception("boom")
class FakeAnthropic:
    def __init__(self, api_key=None):
        self.messages = FakeMessages()
fake_anthropic.Anthropic = FakeAnthropic
sys.modules["anthropic"] = fake_anthropic

import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [9000]
    def __init__(self, chat_id, edit_should_fail=True):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.sent = []
        self.edited = []
        self.last_reply = None
        self.edit_should_fail = edit_should_fail
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        child = FakeMsg(self.chat_id, edit_should_fail=False)
        self.last_reply = child
        return child
    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
        if self.edit_should_fail:
            raise Exception("message is not modified")


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, text="", args=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.message = FakeMsg(uid)
        self.message.text = text
        self.callback_query = None
        self.args = args


class FakeCtxBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        m = FakeMsg(chat_id)
        self.sent.append((chat_id, text, kw.get("reply_markup"), m.message_id))
        return m
    async def delete_message(self, chat_id, message_id):
        pass
    async def edit_message_text(self, chat_id, message_id, text, **kw):
        raise Exception("message is not modified")


class FakeCtx:
    def __init__(self, args=None):
        self.user_data = {}
        self.bot = FakeCtxBot()
        self.args = args or []


def has_menu_button(reply_markup):
    if reply_markup is None:
        return False
    for row in reply_markup.inline_keyboard:
        for btn in row:
            if btn.callback_data == "go_menu":
                return True
    return False


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real gap: several dead-end retry/error screens sent a brand new
    # message (reply_text/edit_text fallback) with NO reply_markup at all --
    # no way back to the menu without typing /start. Each of these now
    # carries a "◀️ Меню" (or equivalent Cancel) button.
    # ══════════════════════════════════════════════════════════════════════

    # 1. send_coach exception path (ctx is not None branch).
    ctx = FakeCtx()
    msg = FakeMsg(uid)
    await bot.send_coach(msg, "привет", uid, ctx=ctx)
    assert msg.sent, "expected a fallback reply on the passed-in message"
    last_sent = msg.sent[-1]
    assert has_menu_button(last_sent[1]), f"coach error message has no Меню button: {last_sent}"
    print("1. send_coach exception path carries a Меню button")

    # 1b. send_coach exception path (ctx is None branch).
    msg2 = FakeMsg(uid)
    await bot.send_coach(msg2, "привет", uid, ctx=None)
    thinking = msg2.last_reply
    assert thinking is not None and thinking.edited, "expected thinking.edit_text to have been called"
    assert has_menu_button(thinking.edited[-1][1]), f"coach error (no ctx) has no Меню button: {thinking.edited}"
    print("1b. send_coach exception path (no ctx) carries a Меню button")

    # 2. awaiting_time bad format retry.
    ctx = FakeCtx()
    ctx.user_data["awaiting_time"] = True
    upd = FakeUpdate(uid, text="not-a-time")
    await bot.handle_text(upd, ctx)
    assert upd.message.sent, "expected a fallback reply"
    assert has_menu_button(upd.message.sent[-1][1]), f"awaiting_time retry has no Меню button: {upd.message.sent}"
    print("2. awaiting_time retry carries a Меню button")

    # 3. awaiting_name empty retry.
    ctx = FakeCtx()
    ctx.user_data["awaiting_name"] = True
    upd = FakeUpdate(uid, text="   ")
    await bot.handle_text(upd, ctx)
    assert has_menu_button(upd.message.sent[-1][1]), f"awaiting_name empty retry has no Меню button: {upd.message.sent}"
    print("3. awaiting_name (empty) retry carries a Меню button")

    # 4. awaiting_name too long retry.
    ctx = FakeCtx()
    ctx.user_data["awaiting_name"] = True
    upd = FakeUpdate(uid, text="x" * 40)
    await bot.handle_text(upd, ctx)
    assert has_menu_button(upd.message.sent[-1][1]), f"awaiting_name too-long retry has no Меню button: {upd.message.sent}"
    print("4. awaiting_name (too long) retry carries a Меню button")

    # 5. awaiting_reminder_add unparseable retry.
    ctx = FakeCtx()
    ctx.user_data["awaiting_reminder_add"] = True
    upd = FakeUpdate(uid, text="совершенно непонятный текст без времени")
    await bot.handle_text(upd, ctx)
    assert has_menu_button(upd.message.sent[-1][1]), f"awaiting_reminder_add retry has no Меню button: {upd.message.sent}"
    print("5. awaiting_reminder_add retry carries a Меню button")

    # 6. awaiting_reminder_edit unparseable retry.
    bot.add_reminder(uid, "тест", "2099-01-01T10:00:00", "")
    rem_id = bot.get_reminders(uid)[0]["id"]
    ctx = FakeCtx()
    ctx.user_data["awaiting_reminder_edit"] = rem_id
    upd = FakeUpdate(uid, text="совершенно непонятный текст без времени")
    await bot.handle_text(upd, ctx)
    assert has_menu_button(upd.message.sent[-1][1]), f"awaiting_reminder_edit retry has no Меню button: {upd.message.sent}"
    print("6. awaiting_reminder_edit retry carries a Меню button")

    # 7. awaiting_work_start bad format retry.
    ctx = FakeCtx()
    ctx.user_data["awaiting_work_start"] = True
    upd = FakeUpdate(uid, text="not-a-time")
    await bot.handle_text(upd, ctx)
    assert has_menu_button(upd.message.sent[-1][1]), f"awaiting_work_start retry has no Меню button: {upd.message.sent}"
    print("7. awaiting_work_start retry carries a Меню button")

    # 8. /promo with no args.
    ctx = FakeCtx(args=[])
    upd = FakeUpdate(uid, args=[])
    await bot.promo_command(upd, ctx)
    assert upd.message.sent, "expected a fallback reply on update.message"
    assert has_menu_button(upd.message.sent[-1][1]), f"/promo (no args) has no Cancel/Меню button: {upd.message.sent}"
    print("8. /promo (no args) carries a Cancel button")

    print("\nALL DEAD-END-MENU-BUTTON TESTS PASSED")


asyncio.run(main())
