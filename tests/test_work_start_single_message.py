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
    # actually set (see ask_work_start_after_tasks).
    #
    # morning_task_offer_yes ("Да, поставить" after the morning ritual) now
    # jumps straight into the step-by-step walk (Задача A first), editing
    # the tapped ritual-finale message itself in place -- see
    # test_morning_tasks_yes_direct.py for that fix. It arms the deferred
    # work-start flag but does NOT show a separate task-overview screen.
    # ══════════════════════════════════════════════════════════════════════
    finale_msg = FakeMsg(chat_id=uid)
    ctx = FakeCtx()
    upd = FakeUpdate(uid, data="morning_tasks_yes", message=finale_msg)
    await bot.morning_task_offer_yes(upd, ctx)
    assert finale_msg.edited, "must take over the ritual finale message in place (Задача A prompt)"
    assert not finale_msg.reply_calls, "must not also send a separate task-overview screen"
    assert ctx.user_data.get("ask_work_start_after_tasks"), \
        "the work-start question must be deferred until a task is actually set"
    print("1a. morning_task_offer_yes jumps straight to the Task A prompt (in place), defers the work-start question")

    # Setting Task A via the walk continues on to slot B1 (not the deferred
    # prompt yet -- the walk isn't done). Finishing the walk early via
    # "✅ Готово" is what finally triggers the deferred prompt, as its own
    # new tracked message -- exercised the same way check 1 in
    # test_work_start_after_walk_and_stale.py does.
    await bot.apply_task_edit(finale_msg, ctx, uid, "focus", "Сделать план")
    assert not any("Во сколько" in t for t, _ in finale_msg.reply_calls), \
        "must not fire the work-start prompt mid-walk, right after just Task A"
    assert ctx.user_data.get("ask_work_start_after_tasks"), "flag must survive the mid-walk save"

    walk_msg = FakeMsg(chat_id=uid)
    await bot.walk_finish_callback(FakeUpdate(uid, "walk_finish", walk_msg), ctx)
    assert any("Во сколько" in c[0] for c in walk_msg.reply_calls), \
        f"finishing the walk (even early, via 'Готово') must trigger the deferred prompt, got {walk_msg.reply_calls}"
    prompt_msg = next(c[2] for c in walk_msg.reply_calls if "Во сколько" in c[0])
    assert ctx.user_data.get("work_start_msg_id") == prompt_msg.message_id
    print("1b. Once the walk finishes, the work-start prompt appears as its own new message, tracked")

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
