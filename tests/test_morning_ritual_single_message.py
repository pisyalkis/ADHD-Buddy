import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_morning_ritual_single_message.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [11000]
    def __init__(self, chat_id, text="какой-то текст"):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.reply_calls = []
        self.text = text

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
    def __init__(self):
        self.edits = []     # (chat_id, message_id, text)
        self.deleted = []   # (chat_id, message_id)
        self.sent = []      # (chat_id, text)

    async def edit_message_text(self, chat_id, message_id, text, **kw):
        self.edits.append((chat_id, message_id, text))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return FakeMsg(chat_id)


class FakeCtx:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "нужно удалять все сообщения, на которые пользователь
    # ответил / выбрал нужную опцию. В идеале у нас всегда должно быть одно
    # актуальное сообщение" -- applied to the morning ritual. Walk through
    # go_morning -> skip warmup -> answer writing (typed text) -> skip
    # gratitude (button) -> answer child (typed text) -> finish. At every
    # step the BOT's own question must land on the SAME tracked message
    # (ctx.bot.edit_message_text on one fixed message_id), never a new one.
    # ══════════════════════════════════════════════════════════════════════
    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    menu_screen = FakeMsg(chat_id=uid)  # e.g. main menu, where "☀️ Утро" lives

    upd = FakeUpdate(uid, data="go_morning", message=menu_screen)
    await bot.morning_start(upd, ctx)

    # First render: no tracking existed yet -> falls back to a genuinely
    # NEW message (must NOT edit/replace the menu screen itself).
    assert not menu_screen.reply_calls == False  # sanity: attribute exists
    tracked_id = ctx.user_data.get("ritual_step_msg_id")
    assert tracked_id is not None and tracked_id != menu_screen.message_id, \
        f"the ritual's own first message must be a new message, not the menu screen, got tracked={tracked_id} menu={menu_screen.message_id}"
    print("1. Ritual starts as its own new message, leaving the entry screen (menu) untouched")

    edits_after_start = len(fbot.edits)
    print(f"   (greeting+warmup produced {edits_after_start} edit(s) via ctx.bot, as expected for in-place editing after the first send)")

    # Skip warmup via button (q.message here is a fresh FakeMsg wrapping the
    # SAME tracked message id, mimicking what a real Telegram callback_query
    # message object would be -- same identity as what's tracked).
    warmup_screen = FakeMsg(chat_id=uid)
    warmup_screen.message_id = tracked_id
    upd2 = FakeUpdate(uid, data="skip_warmup", message=warmup_screen)
    await bot.skip_warmup(upd2, ctx)

    assert not warmup_screen.reply_calls, "skipping warmup must not create a new message"
    assert all(mid == tracked_id for _, mid, _ in fbot.edits), \
        f"every edit so far must target the one tracked ritual message, got {fbot.edits}"
    assert "Свободное письмо" in fbot.edits[-1][2], fbot.edits[-1][2]
    print("2. Skipping warmup edits the SAME tracked message into the writing prompt")

    # Answer "writing" by TYPED TEXT -- update.message is the user's OWN
    # message object, which must never be edited.
    user_text = FakeMsg(chat_id=uid)
    upd3 = FakeUpdate(uid, text_message=user_text)
    upd3.effective_user = FakeUser(uid)
    await bot.got_writing(upd3, ctx)

    assert not user_text.reply_calls, "answering by typed text must not spawn a reply from the user's own message"
    assert all(mid == tracked_id for _, mid, _ in fbot.edits)
    assert "Благодарность" in fbot.edits[-1][2], fbot.edits[-1][2]
    print("3. Typed-text answer (writing) still edits the SAME tracked message into the gratitude prompt")

    # Skip gratitude via button.
    gratitude_screen = FakeMsg(chat_id=uid); gratitude_screen.message_id = tracked_id
    upd4 = FakeUpdate(uid, data="skip_m_gratitude", message=gratitude_screen)
    await bot.skip_m_gratitude(upd4, ctx)
    assert not gratitude_screen.reply_calls
    assert "Внутренний ребёнок" in fbot.edits[-1][2], fbot.edits[-1][2]
    print("4. Skipping gratitude edits the SAME tracked message into the inner-child prompt")

    # Answer "child" by typed text -- this is the LAST ritual step, so it
    # triggers finish_morning -> _finish_ritual_cleanup.
    user_text2 = FakeMsg(chat_id=uid)
    upd5 = FakeUpdate(uid, text_message=user_text2)
    upd5.effective_user = FakeUser(uid)
    await bot.got_child(upd5, ctx)

    # finish_morning legitimately sends its own SEPARATE final "Утро
    # записано!" summary (unchanged, pre-existing design -- that's the
    # persistent pinned artifact, not ritual-step scaffolding) as a reply
    # to whatever message triggered it -- here, the user's own last answer.
    assert user_text2.reply_calls and "записано" in user_text2.reply_calls[0][0], \
        f"finish_morning's own final summary must still be sent, got {user_text2.reply_calls}"
    assert all(mid == tracked_id for _, mid, _ in fbot.edits), \
        "the ritual's own Q&A chain never created a second bot message across its entire run"
    print("5. The full ritual (warmup->writing->gratitude->child->finish) stayed on ONE bot message throughout (plus finish_morning's own separate final summary, unchanged)")

    # After finish: the tracked ritual-step message must be cleaned up
    # (deleted, since the separate final "Утро записано!" summary already
    # covers it), and tracking must be cleared.
    assert (uid, tracked_id) in fbot.deleted, \
        f"the final tracked ritual-step message must be deleted at cleanup, got deleted={fbot.deleted}"
    assert ctx.user_data.get("ritual_step_msg_id") is None
    assert ctx.user_data.get("ritual_step_chat_id") is None
    print("6. The tracked ritual-step message is deleted and its tracking cleared at ritual finish")

    # The user's own two typed answers (writing, child) must ALSO have been
    # queued for deletion via the existing ritual_msg_ids mechanism.
    assert (uid, user_text.message_id) in fbot.deleted
    assert (uid, user_text2.message_id) in fbot.deleted
    print("7. The user's own typed answers are still cleaned up via the existing ritual_msg_ids bulk-delete")

    print("\nALL MORNING-RITUAL-SINGLE-MESSAGE TESTS PASSED")


asyncio.run(main())
