import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_work_start_single_message.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [222000]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.edited = []
        self.reply_calls = []

    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
        return self

    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        self.reply_calls.append((text, kw.get("reply_markup"), m))
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
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real request: the work-start question used to fire immediately, right
    # next to a still-EMPTY task screen. It's now deferred until a task is
    # actually set (see ask_work_start_after_tasks) -- morning_task_offer_yes
    # itself must send only the (empty) task screen and nothing else.
    # ══════════════════════════════════════════════════════════════════════
    finale_msg = FakeMsg(chat_id=uid)
    ctx = FakeCtx()
    upd = FakeUpdate(uid, data="morning_tasks_yes", message=finale_msg)
    await bot.morning_task_offer_yes(upd, ctx)
    assert not finale_msg.edited, "the ritual finale message must not be edited"
    assert len(finale_msg.reply_calls) == 1, finale_msg.reply_calls  # just the (empty) task screen
    assert ctx.user_data.get("ask_work_start_after_tasks"), \
        "the work-start question must be deferred until a task is actually set"
    print("1a. morning_task_offer_yes shows only the (still empty) task screen, defers the work-start question")

    # Simulating actually setting a task (any of the non-walk paths funnel
    # through apply_task_edit) is what finally triggers the deferred prompt
    # -- as its own new message, tracked exactly like before.
    task_screen_msg = finale_msg.reply_calls[0][2]
    await bot.apply_task_edit(task_screen_msg, ctx, uid, "focus", "Сделать план")
    assert len(task_screen_msg.reply_calls) == 2, task_screen_msg.reply_calls  # confirm + prompt
    assert "Во сколько" in task_screen_msg.reply_calls[1][0]
    prompt_msg = task_screen_msg.reply_calls[1][2]
    assert ctx.user_data.get("work_start_msg_id") == prompt_msg.message_id
    print("1b. Once a task is actually set, the work-start prompt appears as its own new message, tracked")

    ctx.bot = FakeBot(prompt_msg)
    user_text = FakeMsg(chat_id=uid)
    user_text.text = "bad format"
    upd2 = FakeUpdate(uid, text_message=user_text)
    await bot.handle_text(upd2, ctx)
    assert not user_text.reply_calls, "invalid-format retry must not spawn a new message"
    assert "Неверный формат" in prompt_msg.edited[-1][0], prompt_msg.edited
    print("2. Invalid-format retry edits the SAME tracked prompt message")

    user_text2 = FakeMsg(chat_id=uid)
    user_text2.text = "10:00"
    upd3 = FakeUpdate(uid, text_message=user_text2)
    await bot.handle_text(upd3, ctx)
    assert not user_text2.reply_calls, "the confirmation must not spawn a new message"
    assert "Хорошо" in prompt_msg.edited[-1][0], prompt_msg.edited
    print("3. Typing a valid time edits the SAME tracked prompt message with the confirmation")

    print("\nALL WORK-START-SINGLE-MESSAGE TESTS PASSED")


asyncio.run(main())
